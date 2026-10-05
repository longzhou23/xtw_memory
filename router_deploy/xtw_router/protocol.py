"""Validate observable causal inputs before any tokenization or model work."""
from __future__ import annotations
from datetime import datetime


class InvalidRequest(ValueError):
    pass


def identifier(value,name):
    if not isinstance(value,str) or not value or len(value)>200:
        raise InvalidRequest(f"{name} must be a nonempty string up to 200 characters")
    return value


def timestamp(value):
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
        if parsed.tzinfo is None:raise ValueError()
        return parsed
    except (AttributeError,ValueError,TypeError) as error:
        raise InvalidRequest("timestamp must be an ISO 8601 string with timezone") from error


def to_record(payload):
    if not isinstance(payload,dict) or not set(payload)<={"request_id","conversation_id","target","prior_context","candidates"}:
        raise InvalidRequest("unknown request fields")
    conversation=identifier(payload.get("conversation_id"),"conversation_id")
    target=payload.get("target")
    if not isinstance(target,dict):raise InvalidRequest("target must be an object")
    known={}
    def message(value,*,current=False):
        if not isinstance(value,dict) or not set(value)<={"message_id","participant_id","timestamp","text","reply_to_message_id","sequence_index","conversation_id"}:
            raise InvalidRequest("unknown message fields")
        mid=identifier(value.get("message_id"),"message_id")
        speaker=identifier(value.get("participant_id"),"participant_id")
        text=value.get("text")
        if not isinstance(text,str) or not text.strip() or len(text)>4096:raise InvalidRequest("text must contain 1–4096 characters")
        ts=timestamp(value.get("timestamp"))
        if value.get("conversation_id",conversation)!=conversation:raise InvalidRequest("foreign conversation message")
        seq=value.get("sequence_index")
        if seq is not None and (type(seq) is not int or seq<0):raise InvalidRequest("sequence_index must be a nonnegative integer")
        reply=value.get("reply_to_message_id")
        if reply is not None:identifier(reply,"reply_to_message_id")
        result={"message_id":mid,"participant_id":speaker,"timestamp":value["timestamp"],"text":text,
                "reply_to_message_id":reply}
        if seq is not None:result["sequence_index"]=seq
        if not current:
            if mid==target["message_id"]:raise InvalidRequest("target leaked into historical input")
            if ts>target_time:raise InvalidRequest("future message in historical input")
            target_seq=target.get("sequence_index")
            if seq is not None and target_seq is not None and seq>=target_seq:raise InvalidRequest("nonpast sequence_index")
            declared={k for k in ("sequence_index","reply_to_message_id") if k in value}
            if mid in known:
                previous,previous_time,previous_declared=known[mid]
                if previous_time!=ts or any(previous[k]!=result[k] for k in ("message_id","participant_id","text")):
                    raise InvalidRequest("conflicting versions of a historical message")
                if any(previous.get(k)!=result.get(k) for k in declared & previous_declared):
                    raise InvalidRequest("conflicting historical message metadata")
                preserved={**previous,**{k:result[k] for k in declared}}
                known[mid]=(preserved,ts,previous_declared|declared)
            else:known[mid]=(result,ts,declared)
        return result
    target=message(target,current=True);target_time=timestamp(target["timestamp"])
    context=payload.get("prior_context",[])
    if not isinstance(context,list) or len(context)>8:raise InvalidRequest("at most 8 prior context messages")
    context=[message(m) for m in context]
    candidates=payload.get("candidates",[])
    if not isinstance(candidates,list) or len(candidates)>8:raise InvalidRequest("at most 8 candidates")
    mapped=[];episode_ids=set()
    for candidate in candidates:
        if not isinstance(candidate,dict) or not set(candidate)<={"episode_id","conversation_id","member_message_ids","first_messages","recent_messages","summary"}:
            raise InvalidRequest("unknown candidate fields")
        eid=identifier(candidate.get("episode_id"),"episode_id")
        if eid in episode_ids:raise InvalidRequest("duplicate episode_id")
        episode_ids.add(eid)
        if candidate.get("conversation_id",conversation)!=conversation:raise InvalidRequest("foreign conversation candidate")
        members=candidate.get("member_message_ids",[])
        if not isinstance(members,list) or len(members)>4096:raise InvalidRequest("at most 4096 member_message_ids")
        members=[identifier(mid,"member_message_id") for mid in members]
        if len(set(members))!=len(members):raise InvalidRequest("duplicate member_message_ids")
        if target["message_id"] in members:raise InvalidRequest("target leaked into candidate membership")
        first=candidate.get("first_messages",[]);recent=candidate.get("recent_messages",[])
        if not isinstance(first,list) or len(first)>1 or not isinstance(recent,list) or len(recent)>2:raise InvalidRequest("one first and two recent messages maximum")
        first=[message(m) for m in first];recent=[message(m) for m in recent]
        observed={m["message_id"] for m in first+recent}
        if not observed<=set(members):raise InvalidRequest("candidate snippets must be actual members")
        summary=candidate.get("summary","")
        if not isinstance(summary,str) or len(summary)>256:raise InvalidRequest("summary must contain at most 256 characters")
        if not first and not recent and not summary.strip():raise InvalidRequest("candidate needs observable text")
        mapped.append({"runtime_episode_id":eid,"all_episode_message_ids":members,"first_messages":first,"recent_messages":recent,"summary":summary})
    request_id=identifier(payload.get("request_id",target["message_id"]),"request_id")
    # A snippet may omit optional metadata that was supplied for the same real
    # message in context. Return the validated union for every copy; otherwise
    # an absent reply becomes an explicit None and contradicts the known reply
    # when this normalized record is serialized or normalized a second time.
    context=[dict(known[m["message_id"]][0]) for m in context]
    for candidate in mapped:
        for field in ("first_messages","recent_messages"):
            candidate[field]=[dict(known[m["message_id"]][0]) for m in candidate[field]]
    return {"packet":{"case_id":request_id,"conversation_id":conversation,"target_message_id":target["message_id"],
            "target":target,"prior_context":context},"mapped":{"candidates":mapped}}


def from_record(record):
    packet=record["packet"]
    return {"request_id":packet["case_id"],"conversation_id":packet["conversation_id"],"target":packet["target"],
            "prior_context":packet.get("prior_context",[])[-8:],"candidates":[{
                "episode_id":c["runtime_episode_id"],"member_message_ids":c["all_episode_message_ids"],
                "first_messages":c.get("first_messages",[])[:1],"recent_messages":c.get("recent_messages",[])[-2:],
                "summary":c.get("summary","")[:256]} for c in record["mapped"]["candidates"]]}
