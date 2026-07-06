curl -sS -X POST http://127.0.0.1:8080/query \
    -H "content-type: application/json" \
    -d '{
    "tenant_id": "default",
    "question": "who is Gloom Under Night?",
    "mode": "hybrid"
}' | python3 -m json.tool