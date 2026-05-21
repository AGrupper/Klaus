import os
from google.cloud import firestore

db = firestore.Client(project="klaus-agent", database="klaus-firestore")
doc_ref = db.collection("conversations").document("8626312520")
doc = doc_ref.get()

if doc.exists:
    data = doc.to_dict()
    print("Conversation found!")
    messages = data.get("messages", [])
    for idx in range(18, 27):
        m = messages[idx]
        print(f"\n--- MESSAGE {idx} ---")
        print(f"Role: {m.get('role')}")
        content = m.get('content')
        print(f"Type: {type(content)}")
        print(f"Representation: {repr(content)}")
