import os
from google.cloud import firestore

db = firestore.Client(project="klaus-agent", database="klaus-firestore")
doc_ref = db.collection("conversations").document("8626312520")
doc = doc_ref.get()

if doc.exists:
    data = doc.to_dict()
    print("Conversation found!")
    messages = data.get("messages", [])
    print(f"Total messages: {len(messages)}")
    for idx, m in enumerate(messages[-10:]):
        print(f"\n--- MESSAGE {len(messages) - 10 + idx} ---")
        print(f"Role: {m.get('role')}")
        content = m.get('content')
        print(f"Type: {type(content)}")
        print(f"Content: {content}")
