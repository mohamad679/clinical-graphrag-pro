import asyncio
import os
import sys

# Add the backend directory to the Python path so we can import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.graph import temporal_graph_service
from app.services.vector_store import vector_store_service

# Synthetic MIMIC-IV styled patient profiles
PATIENTS = [
    {
        "id": "Patient_1001",
        "label": "Patient",
        "properties": {"age": 58, "gender": "M", "blood_type": "O+"},
        "diseases": [
            ("Type_2_Diabetes", "2015-03-10", None),
            ("Hypertension", "2018-07-22", None),
            ("Diabetic_Neuropathy", "2022-11-05", None)
        ],
        "medications": [
            ("Metformin", "2015-03-15", None, "500mg BID"),
            ("Lisinopril", "2018-07-25", None, "10mg QD"),
            ("Gabapentin", "2022-11-10", None, "300mg TID")
        ],
        "labs": [
            ("HbA1c", "2023-12-01", "8.2%"),
            ("Creatinine", "2023-12-01", "1.1 mg/dL")
        ],
        "narrative": """
        Admission Note - Patient 1001
        Date: 2024-01-15
        Chief Complaint: Numbness and tingling in bilateral lower extremities.
        
        History of Present Illness: 58-year-old male with a history of poorly controlled Type 2 Diabetes initially diagnosed in 2015, and Essential Hypertension since 2018. He presents today with worsening peripheral neuropathy, initially noted in late 2022. He reports a burning sensation in his feet that keeps him awake at night.
        
        Current Medications:
        - Metformin 500mg PO BID (started 2015)
        - Lisinopril 10mg PO daily (started 2018)
        - Gabapentin 300mg PO TID (titrated up in 2022 due to neuropathy)
        
        Recent Labs (Dec 2023): HbA1c remains elevated at 8.2%. Renal function is stable with Creatinine at 1.1 mg/dL.
        
        Plan: Increase Gabapentin to 600mg TID for symptom control. Counsel patient extensively on diet and glycemic control to prevent further microvascular complications. Follow up ophthalmology to check for retinopathy.
        """
    },
    {
        "id": "Patient_2045",
        "label": "Patient",
        "properties": {"age": 72, "gender": "F", "blood_type": "A-"},
        "diseases": [
            ("Atrial_Fibrillation", "2020-05-14", None),
            ("Congestive_Heart_Failure", "2021-09-30", None),
            ("Acute_Kidney_Injury", "2024-02-10", "2024-02-18") # Resolved AKI
        ],
        "medications": [
            ("Apixaban", "2020-05-15", None, "5mg BID"),
            ("Furosemide", "2021-10-01", "2024-02-10", "40mg QD"), # Stopped during AKI
            ("Metoprolol", "2020-05-15", None, "25mg QD")
        ],
        "labs": [
            ("BNP", "2024-02-10", "850 pg/mL"),
            ("Creatinine", "2024-02-10", "2.8 mg/dL"), # Elevated during AKI
            ("Creatinine", "2024-02-18", "1.3 mg/dL")  # Resolving
        ],
        "narrative": """
        Discharge Summary - Patient 2045
        Admission Date: 2024-02-10
        Discharge Date: 2024-02-18
        
        Diagnoses:
        1. Acute Kidney Injury (AKI) secondary to over-diuresis
        2. Congestive Heart Failure (CHF) exacerbation
        3. Atrial Fibrillation (persistant)
        
        Hospital Course: 72-year-old female with a history of Afib on Eliquis (Apixaban) and CHF on Lasix (Furosemide) presented to the ED with weakness and decreased urine output. Admission labs showed a significant bump in Creatinine to 2.8 mg/dL from her baseline of 1.2, consistent with AKI. Her BNP was 850 indicating concurrent mild CHF exacerbation. 
        
        It was determined her AKI was prerenal, likely due to chronic over-diuresis from Furosemide in the outpatient setting. 
        Furosemide was immediately held on 2024-02-10. She was given careful IV fluid resuscitation. Over 8 days, her renal function steadily improved. By discharge on 2024-02-18, her Creatinine had downtrended to 1.3 mg/dL.
        
        Discharge Meds:
        - Metoprolol Succinate 25mg daily
        - Apixaban (Eliquis) 5mg BID (continued for stroke prophylaxis in setting of Afib)
        - HOLD Furosemide. Will re-evaluate need for diuretic at outpatient follow-up in 1 week.
        """
    },
    {
        "id": "Patient_3099",
        "label": "Patient",
        "properties": {"age": 45, "gender": "F", "blood_type": "B+"},
        "diseases": [
            ("Asthma", "1995-01-01", None),
            ("Major_Depressive_Disorder", "2019-04-12", None),
            ("Migraine", "2010-08-05", None)
        ],
        "medications": [
            ("Albuterol_Inhaler", "1995-01-01", None, "PRN"),
            ("Sertraline", "2019-04-15", "2023-11-01", "50mg QD"), # Discontinued
            ("Fluoxetine", "2023-11-01", None, "20mg QD"), # Switched to
            ("Sumatriptan", "2010-08-05", None, "50mg PRN")
        ],
        "labs": [],
        "narrative": """
        Outpatient Clinic Note - Patient 3099
        Date: 2023-12-15
        
        Patient is a 45 y.o. female following up for depression management. She carries a history of lifelong Asthma (well controlled on PRN Albuterol) and chronic migraines.
        
        Psychiatric history: Diagnosed with Major Depressive Disorder in 2019. She was initially started on Sertraline which provided partial relief, but she reported unacceptable weight gain and lethargy. Consequently, on Nov 1, 2023, Sertraline was discontinued and she was directly transitioned to Fluoxetine 20mg daily. 
        
        Today, she reports a significant improvement in her mood and energy levels over the last 6 weeks since starting Fluoxetine. She denies any suicidal ideation. 
        
        Migraines: Occur roughly 1-2 times per month. Aborts well with PRN Sumatriptan 50mg. No change needed.
        
        Plan: 
        1. MDD: Continue Fluoxetine 20mg daily.
        2. Migraine: Continue Sumatriptan PRN.
        3. Asthma: Albuterol PRN. Warned patient that beta-blockers (if ever needed for migraines) could exacerbate her asthma, so we will stick to Triptans.
        Return to clinic in 3 months.
        """
    }
]

async def seed_data():
    print("Beginning Clinical Data Ingestion (MIMIC-IV Synthetic Data)...")
    
    # 1. Clear existing graph (optional, but good for a clean seed)
    temporal_graph_service.graph.clear()
    
    # 2. Add Standard Entities (Diseases/Drugs) first to ensure they exist
    standard_entities = {
        "Type_2_Diabetes": "Disease", "Hypertension": "Disease", "Diabetic_Neuropathy": "Disease",
        "Atrial_Fibrillation": "Disease", "Congestive_Heart_Failure": "Disease", "Acute_Kidney_Injury": "Disease",
        "Asthma": "Disease", "Major_Depressive_Disorder": "Disease", "Migraine": "Disease",
        
        "Metformin": "Drug", "Lisinopril": "Drug", "Gabapentin": "Drug",
        "Apixaban": "Drug", "Furosemide": "Drug", "Metoprolol": "Drug",
        "Albuterol_Inhaler": "Drug", "Sertraline": "Drug", "Fluoxetine": "Drug", "Sumatriptan": "Drug",
        
        "HbA1c": "Lab", "Creatinine": "Lab", "BNP": "Lab"
    }
    
    for entity_id, label in standard_entities.items():
         temporal_graph_service.add_entity(entity_id, label)
         
    # 3. Process Patients
    for idx, p in enumerate(PATIENTS):
        print(f"\nProcessing {p['id']}...")
        
        # A. Add to Graph
        temporal_graph_service.add_entity(p["id"], p["label"], p["properties"])
        
        for disease, start, end in p["diseases"]:
            temporal_graph_service.add_temporal_relation(p["id"], disease, "HAS_CONDITION", start, end)
            
        for drug, start, end, dose in p["medications"]:
            temporal_graph_service.add_temporal_relation(p["id"], drug, "PRESCRIBED", start, end, {"dosage": dose})
            
        for lab, date, val in p["labs"]:
            # Labs represent a point-in-time observation, so start and end are the same
            temporal_graph_service.add_temporal_relation(p["id"], lab, "LAB_RESULT", date, date, {"value": val})
            
        # B. Add Narrative to Vector Store
        doc_name = f"clinical_note_{p['id']}.txt"
        print(f"  -> Vectorizing {doc_name}")
        
        vector_store_service.add_document(
            document_id=doc_name,
            document_name=doc_name,
            text=p["narrative"],
            chunk_size=1000,
            overlap=200
        )
            
    # Force save the graph state
    temporal_graph_service.save_graph()
    
    print("\n✅ Ingestion Complete!")
    print(f"Graph Nodes: {temporal_graph_service.graph.number_of_nodes()}")
    print(f"Graph Edges: {temporal_graph_service.graph.number_of_edges()}")
    
if __name__ == "__main__":
    asyncio.run(seed_data())
