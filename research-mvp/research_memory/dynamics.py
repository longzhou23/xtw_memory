"""P0.2-style relation-conditioned dynamics with complete incoming flow traces."""
import collections
import math

from .contracts import Invalid, integer, number

DEFAULTS = {"temperature": 1.0, "flowFloor": .0005, "maxOutflow": .45, "gamma": 1.15,
            "anchor": .08, "threshold": .04, "steps": 8}


def parameters(supplied=None):
    if supplied is not None and (not isinstance(supplied, dict) or set(supplied) - set(DEFAULTS)):
        raise Invalid("未知扩散参数")
    result = {**DEFAULTS, **(supplied or {})}
    for name, low, high in [("temperature", .2, 4), ("flowFloor", 0, 1), ("maxOutflow", 0, 1),
                            ("gamma", 1, 3), ("anchor", 0, 1), ("threshold", 0, 1)]:
        number(result[name], name, low, high)
    integer(result["steps"], "steps", 1, 32)
    return result


def normalize(values):
    total = math.fsum(values.values())
    if total <= 0:
        raise Invalid("权重总和必须大于0")
    return {key: value / total for key, value in values.items() if value > 0}


def arcs(graph, plan, config):
    relations = normalize(plan["relations"])
    result = collections.defaultdict(list)
    for edge in sorted(graph["edges"], key=lambda e: e["id"]):
        effective = edge["strength"] ** (1 / config["temperature"]) * relations.get(edge["relation"], 0)
        if effective <= 0:
            continue
        forward = edge["relation"] != "CAUSAL" or plan["direction"] in ("forward", "both")
        reverse = edge["relation"] != "CAUSAL" or plan["direction"] in ("reverse", "both")
        for source, target, enabled, direction in [(edge["source"], edge["target"], forward, "forward"),
                                                  (edge["target"], edge["source"], reverse, "reverse")]:
            if enabled:
                result[source].append({"source": source, "target": target, "edgeId": edge["id"],
                                       "relation": edge["relation"], "direction": direction, "effective": effective})
    return result


def diffuse(graph, seeds, plan, config, adjacency=None):
    initial = normalize(seeds)
    adjacency = arcs(graph, plan, config) if adjacency is None else adjacency
    state, paths, history = dict(initial), {key: [] for key in initial}, []
    checked = 0
    for step in range(config["steps"]):
        contributions = collections.defaultdict(list)
        flows, discoveries = [], {}
        for source, attention in sorted(state.items()):
            choices = adjacency.get(source, [])
            checked += len(choices)
            eligible = [(arc, max(0, attention * arc["effective"] - config["flowFloor"])) for arc in choices]
            eligible = [(arc, potential) for arc, potential in eligible if potential > 0]
            requested = math.fsum(potential for _, potential in eligible)
            outgoing = min(attention * config["maxOutflow"], requested)
            contributions[source].append(attention - outgoing)
            for arc, potential in eligible:
                amount = outgoing * potential / requested
                if amount <= 0:
                    continue
                contributions[arc["target"]].append(amount)
                flow = {**arc, "amount": amount}
                flows.append(flow)
                if arc["target"] not in paths and (arc["target"] not in discoveries or amount > discoveries[arc["target"]]["amount"]):
                    discoveries[arc["target"]] = flow
        for target, flow in discoveries.items():
            paths[target] = paths[flow["source"]] + [flow]
        raw = {key: math.fsum(values) for key, values in contributions.items()}
        peak = max(raw.values())
        competed = normalize({key: (value / peak) ** config["gamma"] for key, value in raw.items()})
        next_state = {key: (1-config["anchor"]) * competed.get(key, 0) + config["anchor"] * initial.get(key, 0)
                      for key in sorted(set(raw) | set(initial))}
        next_state = {key: value for key, value in next_state.items() if value > 0}
        if abs(math.fsum(raw.values()) - 1) > 1e-10 or abs(math.fsum(next_state.values()) - 1) > 1e-10:
            raise ArithmeticError("注意力不守恒")
        history.append({"step": step+1, "raw": raw, "competed": competed, "state": next_state,
                        "total": math.fsum(next_state.values()), "flows": flows,
                        "emerged": [key for key, value in next_state.items() if value >= config["threshold"]]})
        state = next_state
    return {"state": state, "history": history, "paths": paths, "checkedArcs": checked, "visitedNodes": len(state)}


def graph_expand(graph, seeds, plan, config, adjacency=None):
    """Best-path expansion: identical relation channels, no accumulation/competition."""
    adjacency = arcs(graph, plan, config) if adjacency is None else adjacency
    frontier = normalize(seeds)
    best, paths, checked = dict(frontier), {key: [] for key in frontier}, 0
    layer_paths = dict(paths)
    for _ in range(config["steps"]):
        following, next_paths = {}, {}
        for source, weight in sorted(frontier.items()):
            for arc in adjacency.get(source, []):
                checked += 1
                score = weight * arc["effective"]
                if score > following.get(arc["target"], 0):
                    following[arc["target"]] = score
                    next_paths[arc["target"]] = layer_paths[source] + [arc]
                if score > best.get(arc["target"], 0):
                    best[arc["target"]] = score
                    paths[arc["target"]] = layer_paths[source] + [arc]
        frontier, layer_paths = following, next_paths
    return {"state": best, "paths": paths, "history": [], "checkedArcs": checked, "visitedNodes": len(best)}
