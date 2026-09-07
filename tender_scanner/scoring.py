"""Transparent legal/healthcare relevance scoring."""
from __future__ import annotations
import re

LEGAL_RULES = (
    (r"\bpanel of law firms?\b", 95, "panel of law firms"),
    (r"\blegal services?\b", 90, "legal services"),
    (r"\bexternal legal (?:services?|counsel|advis(?:er|or|ory))\b", 85, "external legal work"),
    (r"\blaw firms?\b", 75, "law firm"),
    (r"\blegal counsel\b", 75, "legal counsel"),
    (r"\blegal (?:advice|advisory|adviser|advisor|consultancy)\b", 65, "legal advisory"),
    (r"\bdata protection\b|\bpdpa\b", 42, "data protection"),
    (r"\bprivacy (?:law|advisory|compliance|review)\b", 38, "privacy"),
    (r"\bemployment law\b|\bindustrial relations\b", 38, "employment"),
    (r"\bregulatory (?:advice|advisory|compliance|review)\b", 36, "regulatory"),
    (r"\bcorporate governance\b|\bboard governance\b", 34, "governance"),
    (r"\bintellectual property\b|\btrade marks?\b", 32, "intellectual property"),
    (r"\bcontract (?:drafting|review|advisory|management)\b", 30, "contracts"),
    (r"\bcompliance (?:advice|advisory|review|framework)\b", 28, "compliance"),
    (r"\bcorporate secretarial\b", 28, "corporate secretarial"),
    (r"\bwhistleblow(?:ing|er)\b|\binvestigation\b", 26, "investigations"),
    (r"\binternal audit\b|\bcontrols self-assessment\b", 22, "assurance/governance"),
    (r"\bjoint venture\b|\bm&a\b|\bmerger(?:s)? and acquisition", 35, "transactions"),
    (r"\barbitration\b|\bmediation\b|\bdispute resolution\b", 35, "disputes"),
)
NEGATIVE_RULES = (
    (r"\b(?:engineering|architectural|quantity surveying)\b", -55, "technical consultancy"),
    (r"\b(?:software|hardware|network|cybersecurity|cloud)\b", -35, "technology services"),
    (r"\b(?:coaching|tuition|training programme|sports?)\b", -38, "training or sports"),
    (r"\b(?:cleaning|catering|guarding|landscaping|pest control)\b", -50, "facilities service"),
    (r"\b(?:installation|maintenance|repair|supply and delivery)\b", -35, "supply or maintenance"),
    (r"\b(?:medical services?|clinical|laboratory)\b", -32, "medical service"),
    (r"\b(?:event management|video production|design and production)\b", -30, "creative or event service"),
)
HEALTHCARE_RULES = (
    (r"\bministry of health\b|\bmoh holdings\b|\bmohh\b", 100, "MOH ecosystem"),
    (r"\bsinghealth\b|\bnhg\b|\bnational university health system\b|\bnuhs\b", 100, "public healthcare cluster"),
    (r"\balps healthcare\b|\bnational kidney foundation\b|\bthe kidney foundation\b", 100, "healthcare procurement source"),
    (r"\bhospital\b|\bmedical centre\b|\bmedical center\b", 80, "healthcare institution"),
    (r"\bnursing home\b|\bcommunity care\b|\beldercare\b|\bsenior care\b", 75, "community care"),
    (r"\bhealth sciences authority\b|\bhsa\b", 80, "health regulator"),
    (r"\bhealth promotion board\b|\bhpb\b|\bagency for integrated care\b|\baic\b", 80, "healthcare agency"),
    (r"\bsingapore medical council\b|\bsingapore dental council\b|\bsingapore nursing board\b", 75, "health professional regulator"),
)
PRACTICE_RULES = (
    ("Data Protection / Privacy", r"\bdata protection\b|\bprivacy\b|\bpdpa\b"),
    ("Employment", r"\bemployment\b|\bindustrial relations\b"),
    ("Regulatory / Compliance", r"\bregulatory\b|\bcompliance\b|\blicen[cs]ing\b"),
    ("Corporate / Commercial", r"\bcontract\b|\bcorporate\b|\bjoint venture\b|\bm&a\b"),
    ("Governance / Risk", r"\bgovernance\b|\binternal audit\b|\brisk management\b|\bcontrols self-assessment\b"),
    ("Disputes", r"\bdispute\b|\barbitration\b|\bmediation\b|\blitigation\b"),
    ("Intellectual Property", r"\bintellectual property\b|\btrade marks?\b|\bcopyright\b"),
)

def _score(text: str, rules) -> tuple[int, list[str]]:
    normalized=" ".join((text or "").lower().split()); score=0; reasons=[]
    for pattern,weight,label in rules:
        if re.search(pattern,normalized): score+=weight; reasons.append(label)
    return max(0,min(100,score)),reasons

def legal_score(text: str) -> tuple[int, list[str]]:
    normalized=" ".join((text or "").lower().split())
    score,reasons=_score(normalized,LEGAL_RULES+NEGATIVE_RULES)
    if re.search(r"\b(?:legal services?|panel of law firms?|legal counsel|law firms?)\b",normalized):
        score=max(score,75)
    return score,reasons

def healthcare_score(text: str) -> tuple[int,list[str]]:
    return _score(text,HEALTHCARE_RULES)

def relevance_label(score:int)->str:
    return "high" if score>=60 else "review" if score>=28 else "low"

def classify_practice_areas(text:str)->list[str]:
    normalized=" ".join((text or "").lower().split())
    return [label for label,pattern in PRACTICE_RULES if re.search(pattern,normalized)]

def enrich(record:dict,extra_text:str="")->dict:
    text=" ".join(str(record.get(key) or "") for key in ("title","agency","source","summary"))+" "+extra_text
    legal,legal_reasons=legal_score(text); healthcare,healthcare_reasons=healthcare_score(text)
    return {**record,"legal_relevance_score":legal,"relevance_score":legal,"relevance":relevance_label(legal),"healthcare_relevance_score":healthcare,"sector":"Healthcare" if healthcare>=70 else "Other","practice_areas":classify_practice_areas(text),"score_reasons":legal_reasons,"healthcare_reasons":healthcare_reasons}
