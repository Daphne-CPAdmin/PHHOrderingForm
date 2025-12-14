#!/bin/bash
# Pre-commit hook to validate syntax before committing
# To install: ln -s ../../.pre-commit-hook.sh .git/hooks/pre-commit

echo "🔍 Running syntax validation..."

python3 pre_update_validation.py

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Syntax validation failed! Please fix errors before committing."
    exit 1
fi

echo "✅ Syntax validation passed!"
exit 0

