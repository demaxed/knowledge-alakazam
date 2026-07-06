TENANT_ID=default
n=0

find ./sample-docs -maxdepth 1 -type f | sort | head -10 | while read -r file; do
    n=$((n + 1))
    source_id=$(printf "doc-%02d" "$n")

    echo "Uploading $file as $source_id"

    curl -sS -X POST http://127.0.0.1:8080/ingest \
        -F "tenant_id=${TENANT_ID}" \
        -F "source_id=${source_id}" \
        -F "file=@${file}" \
        | python -m json.tool
done