"""Offline experimental two-judge adapter; no production acceptance."""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import resource
import time
from .protocol import to_record

INPUT_VERSION = 'two-judge-observable-v3'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def make_questions(payload):
    record = to_record(payload)
    candidates = record['mapped']['candidates']
    if not candidates: raise ValueError('feature encoding requires real candidates')
    target = record['packet']['target']
    context = record['packet']['prior_context'][-8:]
    visible = list(context)
    for c in candidates: visible += c['first_messages'] + c['recent_messages']
    aliases = {}
    for m in visible + [target]:
        aliases.setdefault(m['participant_id'], f'P{len(aliases)+1}')
    def shown(m, limit=None):
        return f"{aliases[m['participant_id']]}: {m['text'] if limit is None else m['text'][:limit]}"
    lines = [shown(m) for m in context]
    reply = target.get('reply_to_message_id')
    reply_message = next((m for m in visible if m['message_id'] == reply), None)
    reply_text = ('\n[回复原文] ' + shown(reply_message, 80) if reply_message else '\n[结构回复] 回复目标原文未呈现') if reply else ''
    target_text = reply_text + '\n[当前消息] ' + shown(target)
    context_text = '[近期上下文]\n' + '\n'.join(lines)
    snippets = []
    criteria, episode_ids = {}, []
    for i, c in enumerate(candidates):
        snip = ' ; '.join(shown(m, 40) for m in (c['recent_messages'][-2:] or c['first_messages'])) or c['summary'][:40]
        tag = ' [包含回复目标]' if reply and reply in c['all_episode_message_ids'] else ''
        snippets.append(f'- 话题 {i+1}{tag}: {snip}')
        # Opaque durable IDs are mapping metadata, never classifier text.
        criteria[f'C{i+1}'] = f'延续话题{tag}: {snip}'
        episode_ids.append(c['runtime_episode_id'])
    seed = int(hashlib.sha256(json.dumps([context_text, snippets, target_text, criteria], ensure_ascii=False).encode()).hexdigest()[:8], 16)
    order = [1, 0] if seed % 2 else [0, 1]
    ranking_order = list(range(len(episode_ids)))
    random.Random(seed).shuffle(ranking_order)
    return {'episode_ids': episode_ids,
            'boundary': {'state': context_text + '\n[活跃候选话题]\n' + '\n'.join(snippets) + target_text,
                         'question': {'t': 'choice', 'ins': '判断当前目标消息是开启独立新话题还是延续已有话题？',
                                      'crit': {'CONTINUE': '延续话题: 属于候选话题之一或群聊历史讨论', 'NEW': '新话题: 开启完全独立的新讨论线程'}},
                         'option_order': order},
            'ranking': {'state': context_text + target_text,
                        'question': {'t': 'choice', 'ins': '当前目标消息延续哪个候选话题？', 'crit': criteria},
                        'option_order': ranking_order}}


def checkpoint_fingerprint(seal):
    files = {b['branch']: {name: info['sha256'] for name, info in b['files'].items()} for b in seal['checkpoints']}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def load_readout(spec, base_sha, dimension=768):
    path = Path(spec['path'])
    if digest(path) != spec['sha256']: raise ValueError('readout seal changed')
    body = json.loads(path.read_text())
    weight = body.get('weight')
    if (body.get('input_version') != INPUT_VERSION
            or body.get('base_seal_sha256') != base_sha
            or not isinstance(weight, list) or len(weight) != dimension
            or any(type(v) not in (float, int) or not math.isfinite(v) for v in weight)):
        raise ValueError('readout shape/version/base/finite-number contract failed')
    return weight


def overlay_values(spec, expected, metadata):
    """Validate a complete subset before any parameter copy."""
    from safetensors import safe_open
    import torch
    path = Path(spec['path'])
    if path.stat().st_size > 100000000 or digest(path) != spec['sha256']:
        raise ValueError('typed overlay size/hash mismatch')
    with safe_open(str(path), framework='pt', device='cpu') as tensors:
        saved = tensors.metadata() or {}
        if any(saved.get(k) != v for k,v in metadata.items()):
            raise ValueError('typed overlay source/branch/version/recipe mismatch')
        if set(tensors.keys()) != set(expected):
            raise ValueError('typed overlay must contain the full head/scorer only')
        values = {}
        for key, value in expected.items():
            section = tensors.get_slice(key)
            if section.get_shape() != list(value.shape) or section.get_dtype() != 'F32':
                raise ValueError('typed overlay shape or dtype differs')
            tensor = tensors.get_tensor(key)
            if not torch.isfinite(tensor).all():
                raise ValueError('typed overlay contains nonfinite weights')
            values[key] = tensor
    return values


def load_overlay(model, spec, base_sha, branch):
    """Replace only a complete, sealed typed head/scorer; validate before copying."""
    expected = {k:v for k,v in model.state_dict().items() if k.startswith(('head.', 'scorer.'))}
    values = overlay_values(spec, expected, {'base_seal_sha256':base_sha, 'branch':branch,
                            'input_version':INPUT_VERSION, 'recipe_sha256':spec['recipe_sha256']})
    for prefix, module in (('head.', model.head), ('scorer.', model.scorer)):
        module.load_state_dict({k[len(prefix):]:v for k,v in values.items() if k.startswith(prefix)}, strict=True)


def load_suffix(model, spec, base_sha):
    layers = getattr(model.encoder, 'layers', ())
    if len(layers) < 2: raise ValueError('encoder needs at least two layers')
    indices = list(range(len(layers)-2, len(layers)))
    prefixes = tuple(f'encoder.layers.{i}.' for i in indices)
    expected = {k:v for k,v in model.state_dict().items() if k.startswith(prefixes)}
    if any(not any(k.startswith(prefix) for k in expected) for prefix in prefixes):
        raise ValueError('both encoder suffix layers must contain weights')
    values = overlay_values(spec, expected, {'base_seal_sha256':base_sha, 'branch':'boundary',
                            'input_version':INPUT_VERSION, 'recipe_sha256':spec['recipe_sha256'],
                            'layers':json.dumps(indices)})
    for i in indices:
        prefix = f'encoder.layers.{i}.'
        layers[i].load_state_dict({k[len(prefix):]:v for k,v in values.items() if k.startswith(prefix)}, strict=True)


class FrozenTwoJudgeCPU:
    """Sealed encoders with identity-invariant observable inputs."""
    def __init__(self, seal_path, *, threshold=.50, max_requests=200,
                 max_passes=400, max_seconds=600, rss_stop_mib=12288, trace_limit=None):
        if threshold not in (.50, .75):
            raise ValueError('only preregistered thresholds .50/.75 are supported')
        if (any(n is not None and (type(n) is not int or n < 1) for n in (max_requests, max_passes, max_seconds))
                or type(rss_stop_mib) is not int or rss_stop_mib < 1
                or (trace_limit is not None and (type(trace_limit) is not int or trace_limit < 0))):
            raise ValueError('positive CPU budgets or explicit None, finite RSS and nonnegative trace_limit required')
        self.threshold, self.max_requests, self.max_passes = threshold, max_requests, max_passes
        self.max_seconds, self.rss_stop_mib = max_seconds, rss_stop_mib
        self.trace_limit = trace_limit
        self.active_seconds = 0
        # Enforce offline loading before importing transformer dependencies.
        for key in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE'): os.environ[key] = '1'
        os.environ['CUDA_VISIBLE_DEVICES'] = ''
        seal_path = Path(seal_path)
        import torch
        import laya
        torch.set_num_threads(4)
        torch.backends.mha.set_fastpath_enabled(False)
        self.torch = torch
        self.requests = self.passes = 0
        self.inputs = []
        seal = json.loads(seal_path.read_text())
        self.identity = {'seal_sha256': digest(seal_path), 'branches': {},
                         'torch': torch.__version__, 'laya': laya.__file__,
                         'input_version': INPUT_VERSION}
        started = time.perf_counter()
        if sorted(b['branch'] for b in seal['checkpoints']) != ['boundary', 'ranking']:
            raise ValueError('two frozen branches required')
        for branch in seal['checkpoints']:
            path = Path(branch['path'])
            for name, saved in branch['files'].items():
                if digest(path / name) != saved['sha256']: raise ValueError('sealed artifact changed')
            if not (path / 'encoder/config.json').is_file() or not (path / 'tokenizer/tokenizer_config.json').is_file():
                raise ValueError('local encoder/tokenizer missing')
            for required in ('model.safetensors', 'rl_agent_config.json', 'encoder/config.json', 'tokenizer/tokenizer_config.json', 'tokenizer/tokenizer.json'):
                if required not in branch['files']: raise ValueError('incomplete model/tokenizer seal')
            loaded = laya.load(str(path), device='cpu', fast=False)
            loaded.model.eval()
            if any(p.device.type != 'cpu' or p.dtype != torch.float32 for p in loaded.model.parameters()):
                raise ValueError('not CPU FP32')
            setattr(self, branch['branch'], loaded)
            self.identity['branches'][branch['branch']] = {
                'path': str(path), 'weight_sha256': branch['files']['model.safetensors']['sha256'],
                'parameters': sum(p.numel() for p in loaded.model.parameters())}
            self.check_rss()
        if 'boundary_readout' in seal and 'typed_head_overlays' in seal:
            raise ValueError('choose one sealed adaptation, not both')
        if 'boundary_encoder_suffix' in seal:
            if 'typed_head_overlays' not in seal: raise ValueError('suffix requires sealed task heads')
            load_suffix(self.boundary.model, seal['boundary_encoder_suffix'], checkpoint_fingerprint(seal))
            self.identity['boundary_encoder_suffix_sha256'] = seal['boundary_encoder_suffix']['sha256']
        if 'typed_head_overlays' in seal:
            if set(seal['typed_head_overlays']) != {'boundary','ranking'}:
                raise ValueError('both typed overlays must be declared')
            self.identity['typed_head_overlays'] = {}
            for branch, spec in seal['typed_head_overlays'].items():
                load_overlay(getattr(self, branch).model, spec, checkpoint_fingerprint(seal), branch)
                self.identity['typed_head_overlays'][branch] = spec['sha256']
        if 'boundary_readout' in seal:
            layer = self.boundary.model.scorer[-1]
            weight = load_readout(seal['boundary_readout'], checkpoint_fingerprint(seal), layer.in_features)
            if tuple(layer.weight.shape) != (1, layer.in_features): raise ValueError('base readout shape differs')
            with torch.no_grad(): layer.weight.copy_(torch.tensor([weight], dtype=torch.float32))
            self.identity['boundary_readout_sha256'] = seal['boundary_readout']['sha256']
        self.active_seconds = time.perf_counter() - started
        self.identity['cold_load_and_hash_seconds'] = self.active_seconds
        self.check_budget()

    def check_rss(self):
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        if peak > self.rss_stop_mib: raise RuntimeError('sampled RSS budget exceeded')
        return peak

    def check_budget(self):
        if self.max_seconds is not None and self.active_seconds >= self.max_seconds:
            raise RuntimeError('active CPU time budget exceeded')

    def forward(self, agent, state, question, order):
        if self.max_passes is not None and self.passes >= self.max_passes: raise RuntimeError('encoder budget exceeded')
        from laya.common import build_sequence, collate_items, QTYPES
        ids, markers = build_sequence(agent.tok, state, question, max_len=1024,
                                      head_max_len=256, option_order=order, truncate_left=True)
        self.last_encoded = {'input_ids': list(ids), 'markers': list(markers),
                             'decoded': agent.tok.decode(ids)}
        item = {'ids': ids, 'markers': markers, 'qtype': QTYPES['choice'],
                'target': [0.] * len(order), 'label': 0}
        batch = collate_items([[item]], pad_id=agent.tok.pad_token_id)
        with self.torch.inference_mode():
            logits, _ = agent.model(*[batch[k] for k in ('input_ids', 'attention_mask', 'marker_pos', 'marker_mask', 'qtype')])
        self.passes += 1
        self.check_rss()
        return self.torch.softmax(logits[0, :len(order)].float(), dim=-1).tolist(), len(ids)

    def route(self, payload):
        record = to_record(payload)
        candidates = record['mapped']['candidates']
        if not candidates:
            return {'decision': 'NEW', 'episode_id': None, 'p_new': None, 'encoder_passes': 0,
                    'reason': 'NO_CANDIDATES_OPERATIONAL'}
        self.check_budget()
        if ((self.max_requests is not None and self.requests >= self.max_requests)
                or (self.max_passes is not None and self.passes + 2 > self.max_passes)):
            raise RuntimeError('inference budget exceeded')
        self.requests += 1
        questions = make_questions(payload)
        episode_ids = questions['episode_ids']
        started = time.perf_counter()
        formatted = []
        def evaluate(agent, state, question, order):
            encoded = {'branch': 'boundary' if agent is self.boundary else 'ranking', 'state': state, 'question': deepcopy(question), 'option_order': list(order)}
            result = self.forward(agent, state, question, order)
            if hasattr(self, 'last_encoded'):
                encoded['encoded'] = deepcopy(self.last_encoded)
            formatted.append(encoded)
            return result
        probabilities, boundary_tokens = evaluate(self.boundary, questions['boundary']['state'], questions['boundary']['question'], questions['boundary']['option_order'])
        p_new = probabilities[questions['boundary']['option_order'].index(1)]
        scores, ranking_tokens = {}, 0
        if p_new < self.threshold:
            ranking = questions['ranking']
            probabilities, ranking_tokens = evaluate(self.ranking, ranking['state'], ranking['question'], ranking['option_order'])
            scores = {episode_ids[ranking['option_order'][i]]: score for i, score in enumerate(probabilities)}
        result = {'decision': 'NEW' if p_new >= self.threshold else 'CONTINUE',
                  'episode_id': None if p_new >= self.threshold else max(episode_ids, key=scores.__getitem__),
                  'p_new': p_new, 'scores': scores, 'encoder_passes': 1 + bool(scores),
                  'boundary_tokens': boundary_tokens, 'ranking_tokens': ranking_tokens,
                  'elapsed_ms': 1000 * (time.perf_counter() - started)}
        self.active_seconds += time.perf_counter() - started
        self.inputs.append({'payload': deepcopy(payload), 'result': deepcopy(result), 'formatted_inputs': formatted})
        limit = getattr(self, 'trace_limit', None)
        if limit is not None:
            del self.inputs[:max(0, len(self.inputs)-limit)]
        self.check_budget()
        return result
