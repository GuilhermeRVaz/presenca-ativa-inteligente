import os
import json
import sys
from dotenv import load_dotenv

# Ensure UTF-8 output just in case
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Load environment variables
load_dotenv()

# We can reuse the Supabase library configuration from the app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.infrastructure.supabase.repositories import SupabaseRepository

# School ID for Escola Décia
SCHOOL_ID = "aac99735-32cb-4615-b2cb-0be315f18374"
JSON_PATH = r"C:\Users\user\.gemini\antigravity-ide\brain\791678fa-7002-480a-95ee-9705b990578a\scratch\parsed_faq.json"

if not os.path.exists(JSON_PATH):
    print(f"Error: Parsed FAQ JSON not found at {JSON_PATH}")
    sys.exit(1)

with open(JSON_PATH, "r", encoding="utf-8") as f:
    faq_items = json.load(f)

print(f"Loaded {len(faq_items)} FAQ items from JSON.")

# Initialize Supabase repository to access the client
repository = SupabaseRepository(timeout=30.0, attempts=3)
client = repository.client

try:
    # 1. Clear existing rows for this school
    print(f"Clearing existing school_knowledge rows for school {SCHOOL_ID}...")
    client.schema("busca_ativa_v2").table("school_knowledge").delete().eq("school_id", SCHOOL_ID).execute()
    print("Clear complete.")
    
    # 2. Bulk insert new rows
    print("Inserting new FAQ items...")
    rows_to_insert = []
    for item in faq_items:
        rows_to_insert.append({
            "school_id": SCHOOL_ID,
            "category": item["category"],
            "question": item["question"],
            "answer": item["answer"],
            "is_active": True
        })
    
    # Supabase allows bulk inserts by passing a list of dicts
    result = client.schema("busca_ativa_v2").table("school_knowledge").insert(rows_to_insert).execute()
    print(f"Successfully inserted {len(result.data)} items into busca_ativa_v2.school_knowledge.")
except Exception as e:
    print(f"An error occurred during ingestion: {e}", file=sys.stderr)
    sys.exit(1)
