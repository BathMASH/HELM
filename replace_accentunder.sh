#!/bin/bash

# Find all .html files and process them
find . -type f -name "*.html" | while read -r file; do
    # Use sed to replace accentunder="false" with an empty string
    if sed -i 's/accentunder="false"//g' "$file"; then
        echo "Modified: $file"
    fi
done

echo "Replacement complete."
