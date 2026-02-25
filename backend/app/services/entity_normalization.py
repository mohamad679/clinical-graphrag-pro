"""
Medical Entity Normalization Service.

Maps extracted clinical entities to canonical concepts in UMLS, SNOMED CT,
RxNorm, and ICD-10. Uses a curated knowledge base for fast deterministic
lookups and falls back to LLM-powered reasoning for unknown entities.
"""

import json
import logging
from datetime import datetime

from app.schemas.entity_normalization import (
    NormalizedEntity,
    NormalizationResponse,
    EntityInput,
)

logger = logging.getLogger(__name__)


# ── Curated Medical Knowledge Base ───────────────────────
# Each entry: canonical_label -> {ontology, concept_id, semantic_type, alt_ontologies}
# alt_ontologies provides cross-references for completeness.

CANONICAL_CONCEPTS: dict[str, dict] = {
    # ── Cardiovascular Diseases ──────────────────────────
    "Myocardial Infarction": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:22298006",
        "semantic_type": "Disease",
        "umls_cui": "C0027051",
        "icd10": "I21.9",
    },
    "Hypertension": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:38341003",
        "semantic_type": "Disease",
        "umls_cui": "C0020538",
        "icd10": "I10",
    },
    "Heart Failure": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:84114007",
        "semantic_type": "Disease",
        "umls_cui": "C0018801",
        "icd10": "I50.9",
    },
    "Atrial Fibrillation": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:49436004",
        "semantic_type": "Disease",
        "umls_cui": "C0004238",
        "icd10": "I48.91",
    },
    "Coronary Artery Disease": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:53741008",
        "semantic_type": "Disease",
        "umls_cui": "C0010054",
        "icd10": "I25.10",
    },
    "Deep Vein Thrombosis": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:128053003",
        "semantic_type": "Disease",
        "umls_cui": "C0149871",
        "icd10": "I82.40",
    },
    "Pulmonary Embolism": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:59282003",
        "semantic_type": "Disease",
        "umls_cui": "C0034065",
        "icd10": "I26.99",
    },
    "Stroke": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:230690007",
        "semantic_type": "Disease",
        "umls_cui": "C0038454",
        "icd10": "I63.9",
    },

    # ── Metabolic / Endocrine ────────────────────────────
    "Type 2 Diabetes Mellitus": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:44054006",
        "semantic_type": "Disease",
        "umls_cui": "C0011860",
        "icd10": "E11.9",
    },
    "Type 1 Diabetes Mellitus": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:46635009",
        "semantic_type": "Disease",
        "umls_cui": "C0011854",
        "icd10": "E10.9",
    },
    "Hyperlipidemia": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:55822004",
        "semantic_type": "Disease",
        "umls_cui": "C0020473",
        "icd10": "E78.5",
    },
    "Hypothyroidism": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:40930008",
        "semantic_type": "Disease",
        "umls_cui": "C0020676",
        "icd10": "E03.9",
    },
    "Obesity": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:414916001",
        "semantic_type": "Disease",
        "umls_cui": "C0028754",
        "icd10": "E66.9",
    },

    # ── Renal ────────────────────────────────────────────
    "Chronic Kidney Disease": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:709044004",
        "semantic_type": "Disease",
        "umls_cui": "C1561643",
        "icd10": "N18.9",
    },
    "Acute Kidney Injury": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:14669001",
        "semantic_type": "Disease",
        "umls_cui": "C0022660",
        "icd10": "N17.9",
    },

    # ── Respiratory ──────────────────────────────────────
    "Asthma": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:195967001",
        "semantic_type": "Disease",
        "umls_cui": "C0004096",
        "icd10": "J45.909",
    },
    "Chronic Obstructive Pulmonary Disease": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:13645005",
        "semantic_type": "Disease",
        "umls_cui": "C0024117",
        "icd10": "J44.1",
    },
    "Pneumonia": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:233604007",
        "semantic_type": "Disease",
        "umls_cui": "C0032285",
        "icd10": "J18.9",
    },
    "COVID-19": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:840539006",
        "semantic_type": "Disease",
        "umls_cui": "C5203670",
        "icd10": "U07.1",
    },

    # ── Oncology ─────────────────────────────────────────
    "Breast Cancer": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:254837009",
        "semantic_type": "Disease",
        "umls_cui": "C0006142",
        "icd10": "C50.919",
    },
    "Lung Cancer": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:93880001",
        "semantic_type": "Disease",
        "umls_cui": "C0242379",
        "icd10": "C34.90",
    },
    "Colorectal Cancer": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:363406005",
        "semantic_type": "Disease",
        "umls_cui": "C0009402",
        "icd10": "C18.9",
    },

    # ── Neurological ─────────────────────────────────────
    "Epilepsy": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:84757009",
        "semantic_type": "Disease",
        "umls_cui": "C0014544",
        "icd10": "G40.909",
    },
    "Alzheimer Disease": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:26929004",
        "semantic_type": "Disease",
        "umls_cui": "C0002395",
        "icd10": "G30.9",
    },
    "Parkinson Disease": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:49049000",
        "semantic_type": "Disease",
        "umls_cui": "C0030567",
        "icd10": "G20",
    },
    "Major Depressive Disorder": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:370143000",
        "semantic_type": "Disease",
        "umls_cui": "C1269683",
        "icd10": "F32.9",
    },
    "Migraine": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:37796009",
        "semantic_type": "Disease",
        "umls_cui": "C0149931",
        "icd10": "G43.909",
    },

    # ── Infectious ───────────────────────────────────────
    "Sepsis": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:91302008",
        "semantic_type": "Disease",
        "umls_cui": "C0243026",
        "icd10": "A41.9",
    },
    "Urinary Tract Infection": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:68566005",
        "semantic_type": "Disease",
        "umls_cui": "C0042029",
        "icd10": "N39.0",
    },

    # ── GI ───────────────────────────────────────────────
    "Gastroesophageal Reflux Disease": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:235595009",
        "semantic_type": "Disease",
        "umls_cui": "C0017168",
        "icd10": "K21.0",
    },
    "Cirrhosis": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:19943007",
        "semantic_type": "Disease",
        "umls_cui": "C0023890",
        "icd10": "K74.60",
    },

    # ── Musculoskeletal ──────────────────────────────────
    "Rheumatoid Arthritis": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:69896004",
        "semantic_type": "Disease",
        "umls_cui": "C0003873",
        "icd10": "M06.9",
    },
    "Osteoarthritis": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:396275006",
        "semantic_type": "Disease",
        "umls_cui": "C0029408",
        "icd10": "M19.90",
    },
    "Osteoporosis": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:64859006",
        "semantic_type": "Disease",
        "umls_cui": "C0029456",
        "icd10": "M81.0",
    },

    # ── Symptoms ─────────────────────────────────────────
    "Chest Pain": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:29857009",
        "semantic_type": "Symptom",
        "umls_cui": "C0008031",
        "icd10": "R07.9",
    },
    "Dyspnea": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:267036007",
        "semantic_type": "Symptom",
        "umls_cui": "C0013404",
        "icd10": "R06.00",
    },
    "Fever": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:386661006",
        "semantic_type": "Symptom",
        "umls_cui": "C0015967",
        "icd10": "R50.9",
    },
    "Edema": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:267038008",
        "semantic_type": "Symptom",
        "umls_cui": "C0013604",
        "icd10": "R60.9",
    },
    "Fatigue": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:84229001",
        "semantic_type": "Symptom",
        "umls_cui": "C0015672",
        "icd10": "R53.83",
    },
    "Nausea": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:422587007",
        "semantic_type": "Symptom",
        "umls_cui": "C0027497",
        "icd10": "R11.0",
    },
    "Headache": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:25064002",
        "semantic_type": "Symptom",
        "umls_cui": "C0018681",
        "icd10": "R51.9",
    },
    "Cough": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:49727002",
        "semantic_type": "Symptom",
        "umls_cui": "C0010200",
        "icd10": "R05.9",
    },

    # ── Procedures ───────────────────────────────────────
    "Coronary Artery Bypass Graft": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:232717009",
        "semantic_type": "Procedure",
        "umls_cui": "C0010055",
    },
    "Percutaneous Coronary Intervention": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:415070008",
        "semantic_type": "Procedure",
        "umls_cui": "C1532338",
    },
    "Colonoscopy": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:73761001",
        "semantic_type": "Procedure",
        "umls_cui": "C0009378",
    },
    "CT Scan": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:77477000",
        "semantic_type": "Procedure",
        "umls_cui": "C0040405",
    },
    "MRI": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:113091000",
        "semantic_type": "Procedure",
        "umls_cui": "C0024485",
    },
    "Echocardiography": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:40701008",
        "semantic_type": "Procedure",
        "umls_cui": "C0013516",
    },
    "Dialysis": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:108241001",
        "semantic_type": "Procedure",
        "umls_cui": "C0011946",
    },
    "Intubation": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:112798008",
        "semantic_type": "Procedure",
        "umls_cui": "C0021925",
    },

    # ── Drugs (RxNorm preferred) ─────────────────────────
    "Metformin": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:6809",
        "semantic_type": "Drug",
        "umls_cui": "C0025598",
    },
    "Lisinopril": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:29046",
        "semantic_type": "Drug",
        "umls_cui": "C0065374",
    },
    "Atorvastatin": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:83367",
        "semantic_type": "Drug",
        "umls_cui": "C0286651",
    },
    "Amlodipine": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:17767",
        "semantic_type": "Drug",
        "umls_cui": "C0051696",
    },
    "Warfarin": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:11289",
        "semantic_type": "Drug",
        "umls_cui": "C0043031",
    },
    "Aspirin": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:1191",
        "semantic_type": "Drug",
        "umls_cui": "C0004057",
    },
    "Ibuprofen": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:5640",
        "semantic_type": "Drug",
        "umls_cui": "C0020740",
    },
    "Omeprazole": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:7646",
        "semantic_type": "Drug",
        "umls_cui": "C0028978",
    },
    "Amoxicillin": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:723",
        "semantic_type": "Drug",
        "umls_cui": "C0002645",
    },
    "Ciprofloxacin": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:2551",
        "semantic_type": "Drug",
        "umls_cui": "C0008809",
    },
    "Prednisone": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:8640",
        "semantic_type": "Drug",
        "umls_cui": "C0032952",
    },
    "Insulin": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:5856",
        "semantic_type": "Drug",
        "umls_cui": "C0021641",
    },
    "Heparin": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:5224",
        "semantic_type": "Drug",
        "umls_cui": "C0019134",
    },
    "Clopidogrel": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:32968",
        "semantic_type": "Drug",
        "umls_cui": "C0070166",
    },
    "Losartan": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:52175",
        "semantic_type": "Drug",
        "umls_cui": "C0126174",
    },
    "Furosemide": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:4603",
        "semantic_type": "Drug",
        "umls_cui": "C0016860",
    },
    "Levothyroxine": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:10582",
        "semantic_type": "Drug",
        "umls_cui": "C0040165",
    },
    "Gabapentin": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:25480",
        "semantic_type": "Drug",
        "umls_cui": "C0060926",
    },
    "Morphine": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:7052",
        "semantic_type": "Drug",
        "umls_cui": "C0026549",
    },
    "Acetaminophen": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:161",
        "semantic_type": "Drug",
        "umls_cui": "C0000970",
    },
    "Hydrochlorothiazide": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:5487",
        "semantic_type": "Drug",
        "umls_cui": "C0020261",
    },
    "Simvastatin": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:36567",
        "semantic_type": "Drug",
        "umls_cui": "C0074554",
    },
    "Rosuvastatin": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:301542",
        "semantic_type": "Drug",
        "umls_cui": "C0381725",
    },
    "Albuterol": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:435",
        "semantic_type": "Drug",
        "umls_cui": "C0001927",
    },
    "Pantoprazole": {
        "ontology": "RxNorm",
        "concept_id": "RxCUI:40790",
        "semantic_type": "Drug",
        "umls_cui": "C0081876",
    },

    # ── Lab Values / Findings ────────────────────────────
    "Anemia": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:271737000",
        "semantic_type": "Finding",
        "umls_cui": "C0002871",
        "icd10": "D64.9",
    },
    "Hyperkalemia": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:14140009",
        "semantic_type": "Finding",
        "umls_cui": "C0020461",
        "icd10": "E87.5",
    },
    "Hyponatremia": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:89627008",
        "semantic_type": "Finding",
        "umls_cui": "C0020625",
        "icd10": "E87.1",
    },
    "Hypoglycemia": {
        "ontology": "SNOMED CT",
        "concept_id": "SCTID:302866003",
        "semantic_type": "Finding",
        "umls_cui": "C0020615",
        "icd10": "E16.2",
    },
}


# ── Synonym Mapping ──────────────────────────────────────
# Maps common abbreviations / alternate names -> canonical label.
# All keys are lowercase for case-insensitive matching.

SYNONYM_MAP: dict[str, str] = {
    # Cardiovascular
    "mi": "Myocardial Infarction",
    "heart attack": "Myocardial Infarction",
    "acute myocardial infarction": "Myocardial Infarction",
    "ami": "Myocardial Infarction",
    "stemi": "Myocardial Infarction",
    "nstemi": "Myocardial Infarction",
    "htn": "Hypertension",
    "high blood pressure": "Hypertension",
    "elevated blood pressure": "Hypertension",
    "bp elevation": "Hypertension",
    "chf": "Heart Failure",
    "congestive heart failure": "Heart Failure",
    "hf": "Heart Failure",
    "heart failure": "Heart Failure",
    "afib": "Atrial Fibrillation",
    "a-fib": "Atrial Fibrillation",
    "af": "Atrial Fibrillation",
    "cad": "Coronary Artery Disease",
    "coronary heart disease": "Coronary Artery Disease",
    "ischemic heart disease": "Coronary Artery Disease",
    "ihd": "Coronary Artery Disease",
    "dvt": "Deep Vein Thrombosis",
    "pe": "Pulmonary Embolism",
    "cva": "Stroke",
    "cerebrovascular accident": "Stroke",
    "brain attack": "Stroke",

    # Metabolic
    "t2dm": "Type 2 Diabetes Mellitus",
    "type 2 diabetes": "Type 2 Diabetes Mellitus",
    "type ii diabetes": "Type 2 Diabetes Mellitus",
    "dm2": "Type 2 Diabetes Mellitus",
    "diabetes mellitus type 2": "Type 2 Diabetes Mellitus",
    "niddm": "Type 2 Diabetes Mellitus",
    "t1dm": "Type 1 Diabetes Mellitus",
    "type 1 diabetes": "Type 1 Diabetes Mellitus",
    "type i diabetes": "Type 1 Diabetes Mellitus",
    "dm1": "Type 1 Diabetes Mellitus",
    "iddm": "Type 1 Diabetes Mellitus",
    "high cholesterol": "Hyperlipidemia",
    "hypercholesterolemia": "Hyperlipidemia",
    "dyslipidemia": "Hyperlipidemia",

    # Renal
    "ckd": "Chronic Kidney Disease",
    "chronic renal disease": "Chronic Kidney Disease",
    "chronic renal failure": "Chronic Kidney Disease",
    "aki": "Acute Kidney Injury",
    "acute renal failure": "Acute Kidney Injury",
    "arf": "Acute Kidney Injury",

    # Respiratory
    "copd": "Chronic Obstructive Pulmonary Disease",
    "chronic bronchitis": "Chronic Obstructive Pulmonary Disease",
    "emphysema": "Chronic Obstructive Pulmonary Disease",
    "covid": "COVID-19",
    "sars-cov-2": "COVID-19",
    "coronavirus": "COVID-19",

    # GI
    "gerd": "Gastroesophageal Reflux Disease",
    "acid reflux": "Gastroesophageal Reflux Disease",
    "reflux": "Gastroesophageal Reflux Disease",
    "liver cirrhosis": "Cirrhosis",
    "hepatic cirrhosis": "Cirrhosis",

    # Neurological
    "alzheimer's": "Alzheimer Disease",
    "alzheimers": "Alzheimer Disease",
    "alzheimer's disease": "Alzheimer Disease",
    "parkinson's": "Parkinson Disease",
    "parkinsons": "Parkinson Disease",
    "parkinson's disease": "Parkinson Disease",
    "mdd": "Major Depressive Disorder",
    "depression": "Major Depressive Disorder",
    "clinical depression": "Major Depressive Disorder",

    # Infectious
    "uti": "Urinary Tract Infection",
    "urine infection": "Urinary Tract Infection",
    "bladder infection": "Urinary Tract Infection",
    "septicemia": "Sepsis",
    "blood poisoning": "Sepsis",

    # Musculoskeletal
    "ra": "Rheumatoid Arthritis",
    "oa": "Osteoarthritis",
    "degenerative joint disease": "Osteoarthritis",
    "djd": "Osteoarthritis",

    # Procedures
    "cabg": "Coronary Artery Bypass Graft",
    "bypass surgery": "Coronary Artery Bypass Graft",
    "pci": "Percutaneous Coronary Intervention",
    "angioplasty": "Percutaneous Coronary Intervention",
    "stenting": "Percutaneous Coronary Intervention",
    "ct": "CT Scan",
    "cat scan": "CT Scan",
    "computed tomography": "CT Scan",
    "magnetic resonance imaging": "MRI",
    "echo": "Echocardiography",
    "echocardiogram": "Echocardiography",

    # Symptoms
    "shortness of breath": "Dyspnea",
    "sob": "Dyspnea",
    "breathlessness": "Dyspnea",
    "difficulty breathing": "Dyspnea",
    "swelling": "Edema",
    "peripheral edema": "Edema",
    "tiredness": "Fatigue",
    "exhaustion": "Fatigue",
    "vomiting": "Nausea",
    "emesis": "Nausea",

    # Drugs
    "tylenol": "Acetaminophen",
    "paracetamol": "Acetaminophen",
    "apap": "Acetaminophen",
    "advil": "Ibuprofen",
    "motrin": "Ibuprofen",
    "lipitor": "Atorvastatin",
    "norvasc": "Amlodipine",
    "coumadin": "Warfarin",
    "plavix": "Clopidogrel",
    "lasix": "Furosemide",
    "synthroid": "Levothyroxine",
    "neurontin": "Gabapentin",
    "protonix": "Pantoprazole",
    "prilosec": "Omeprazole",
    "crestor": "Rosuvastatin",
    "zocor": "Simvastatin",
    "ventolin": "Albuterol",
    "proventil": "Albuterol",
    "cozaar": "Losartan",
    "glucophage": "Metformin",
    "zestril": "Lisinopril",
    "prinivil": "Lisinopril",
    "hctz": "Hydrochlorothiazide",

    # Findings
    "low hemoglobin": "Anemia",
    "low hgb": "Anemia",
    "high potassium": "Hyperkalemia",
    "elevated potassium": "Hyperkalemia",
    "low sodium": "Hyponatremia",
    "low blood sugar": "Hypoglycemia",
    "low glucose": "Hypoglycemia",
}


# ── LLM Normalization Prompt ─────────────────────────────

NORMALIZATION_PROMPT = """You are a medical entity normalization engine.
Given a list of clinical entities, map each one to its canonical concept in standard medical ontologies.

RULES:
- Use SNOMED CT for clinical findings, diseases, and procedures
- Use RxNorm for medications and drugs
- Use UMLS CUI for cross-ontology alignment
- Use ICD-10 as a secondary code when applicable
- Treat synonyms as the same concept
- Assign confidence: High (exact match), Medium (likely match), Low (uncertain)
- If no confident match, set is_ungrounded=true and suggest closest_candidate

Return ONLY a JSON array. Each element must match this structure exactly:
{
  "surface_form": "<original text>",
  "canonical_label": "<normalized name>",
  "ontology": "<UMLS | SNOMED CT | RxNorm | ICD-10>",
  "concept_id": "<CUI/SCTID/RxCUI/ICD code>",
  "semantic_type": "<Disease | Drug | Procedure | Symptom | Finding>",
  "confidence": "<High | Medium | Low>",
  "is_ungrounded": false,
  "closest_candidate": null
}

Entities to normalize:
{entities_json}
"""


class EntityNormalizationService:
    """
    Maps extracted medical entities to canonical concepts in standard ontologies.

    Strategy:
    1. Check synonym map for abbreviation / alternate name resolution
    2. Look up canonical label in the curated knowledge base
    3. Fall back to LLM-powered normalization for unknown entities
    4. Maintain a per-batch session cache for consistency
    """

    def __init__(self) -> None:
        # Build a lowercase lookup index for the curated vocabulary
        self._canonical_index: dict[str, str] = {
            label.lower(): label for label in CANONICAL_CONCEPTS
        }

    # ── Public API ───────────────────────────────────────

    async def normalize(
        self,
        entities: list[EntityInput],
    ) -> NormalizationResponse:
        """
        Normalize a batch of entities, ensuring consistent mapping.
        """
        session_cache: dict[str, NormalizedEntity] = {}
        results: list[NormalizedEntity] = []
        llm_pending: list[EntityInput] = []

        for entity in entities:
            result = self._try_curated_lookup(entity.surface_form, session_cache)
            if result:
                results.append(result)
            else:
                llm_pending.append(entity)

        # Batch LLM call for unknowns
        if llm_pending:
            llm_results = await self._normalize_via_llm(llm_pending)
            for res in llm_results:
                canonical_key = res.canonical_label.lower()
                if canonical_key not in session_cache:
                    session_cache[canonical_key] = res
                results.append(session_cache[canonical_key])

        return NormalizationResponse(
            normalized_entities=results,
            total=len(results),
            timestamp=datetime.utcnow(),
        )

    # ── Curated Lookup ───────────────────────────────────

    def _try_curated_lookup(
        self,
        surface_form: str,
        session_cache: dict[str, NormalizedEntity],
    ) -> NormalizedEntity | None:
        """
        Attempt to resolve via synonym map + curated vocabulary.
        Returns None if no match.
        """
        key = surface_form.strip().lower()

        # Step 1: Check synonym map
        canonical_label = SYNONYM_MAP.get(key)

        # Step 2: If not a synonym, check if the surface form IS a canonical label
        if canonical_label is None:
            canonical_label = self._canonical_index.get(key)

        if canonical_label is None:
            return None

        # Step 3: Return from session cache if already resolved
        cache_key = canonical_label.lower()
        if cache_key in session_cache:
            # Return a new entity with the current surface_form but same mapping
            cached = session_cache[cache_key]
            return NormalizedEntity(
                surface_form=surface_form,
                canonical_label=cached.canonical_label,
                ontology=cached.ontology,
                concept_id=cached.concept_id,
                semantic_type=cached.semantic_type,
                confidence=cached.confidence,
                is_ungrounded=cached.is_ungrounded,
                closest_candidate=cached.closest_candidate,
            )

        # Step 4: Build from curated data
        concept = CANONICAL_CONCEPTS[canonical_label]
        result = NormalizedEntity(
            surface_form=surface_form,
            canonical_label=canonical_label,
            ontology=concept["ontology"],
            concept_id=concept["concept_id"],
            semantic_type=concept["semantic_type"],
            confidence="High",
            is_ungrounded=False,
        )

        session_cache[cache_key] = result
        return result

    # ── LLM Fallback ─────────────────────────────────────

    async def _normalize_via_llm(
        self,
        entities: list[EntityInput],
    ) -> list[NormalizedEntity]:
        """
        Use LLM to normalize entities not found in the curated vocabulary.
        """
        try:
            from app.services.llm import llm_service
        except Exception as e:
            logger.error(f"Could not import LLM service: {e}")
            return self._mark_ungrounded(entities)

        entities_payload = [
            {"surface_form": e.surface_form, "context": e.context or ""}
            for e in entities
        ]

        prompt = NORMALIZATION_PROMPT.replace(
            "{entities_json}", json.dumps(entities_payload, indent=2)
        )

        try:
            raw_response = await llm_service.generate(prompt)
            return self._parse_llm_response(raw_response, entities)
        except Exception as e:
            logger.error(f"LLM normalization failed: {e}")
            return self._mark_ungrounded(entities)

    def _parse_llm_response(
        self,
        raw_response: str,
        original_entities: list[EntityInput],
    ) -> list[NormalizedEntity]:
        """Parse JSON array from LLM response, falling back to ungrounded."""
        # Extract JSON from potential markdown code blocks
        text = raw_response.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        # Find the JSON array boundaries
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            logger.warning("LLM response did not contain a JSON array")
            return self._mark_ungrounded(original_entities)

        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM JSON: {e}")
            return self._mark_ungrounded(original_entities)

        results: list[NormalizedEntity] = []
        for item in parsed:
            try:
                results.append(
                    NormalizedEntity(
                        surface_form=item.get("surface_form", ""),
                        canonical_label=item.get("canonical_label", "Unknown"),
                        ontology=item.get("ontology", "UMLS"),
                        concept_id=item.get("concept_id", "UNKNOWN"),
                        semantic_type=item.get("semantic_type", "Unknown"),
                        confidence=item.get("confidence", "Low"),
                        is_ungrounded=item.get("is_ungrounded", False),
                        closest_candidate=item.get("closest_candidate"),
                    )
                )
            except Exception:
                continue

        # Fill in any missing entities as ungrounded
        resolved_forms = {r.surface_form.lower() for r in results}
        for entity in original_entities:
            if entity.surface_form.lower() not in resolved_forms:
                results.append(
                    NormalizedEntity(
                        surface_form=entity.surface_form,
                        canonical_label=entity.surface_form,
                        ontology="UMLS",
                        concept_id="[UNGROUNDED]",
                        semantic_type="Unknown",
                        confidence="Low",
                        is_ungrounded=True,
                        closest_candidate=None,
                    )
                )

        return results

    # ── Helpers ───────────────────────────────────────────

    @staticmethod
    def _mark_ungrounded(entities: list[EntityInput]) -> list[NormalizedEntity]:
        """Mark all entities as ungrounded when resolution fails."""
        return [
            NormalizedEntity(
                surface_form=e.surface_form,
                canonical_label=e.surface_form,
                ontology="UMLS",
                concept_id="[UNGROUNDED]",
                semantic_type="Unknown",
                confidence="Low",
                is_ungrounded=True,
                closest_candidate=None,
            )
            for e in entities
        ]

    def get_supported_ontologies(self) -> list[dict]:
        """Return metadata about supported ontologies."""
        return [
            {
                "name": "UMLS",
                "code": "CUI",
                "description": "Unified Medical Language System — cross-ontology concept identifiers",
                "preferred_for": ["Cross-ontology alignment"],
            },
            {
                "name": "SNOMED CT",
                "code": "SCTID",
                "description": "Systematized Nomenclature of Medicine — Clinical Terms",
                "preferred_for": ["Diseases", "Symptoms", "Findings", "Procedures"],
            },
            {
                "name": "RxNorm",
                "code": "RxCUI",
                "description": "Normalized names for clinical drugs",
                "preferred_for": ["Drugs", "Medications"],
            },
            {
                "name": "ICD-10",
                "code": "ICD-10-CM",
                "description": "International Classification of Diseases, 10th Revision",
                "preferred_for": ["Billing codes", "Epidemiology"],
            },
        ]


# Module-level singleton
entity_normalization_service = EntityNormalizationService()
