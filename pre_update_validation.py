"""
Pre-update validation script - checks syntax before allowing updates.
Run this before making code changes to ensure no syntax errors.
"""
import sys
from pathlib import Path
from validate_syntax import validate_file


def validate_project_files():
    """Validate all Python and HTML files in the project"""
    project_root = Path(__file__).parent
    
    # Files to validate
    files_to_check = [
        project_root / 'app.py',
        project_root / 'templates' / 'index.html',
        project_root / 'templates' / 'admin.html',
    ]
    
    # Also check for any Python files in components directory if it exists
    components_dir = project_root / 'components'
    if components_dir.exists():
        files_to_check.extend(components_dir.glob('*.py'))
    
    all_valid = True
    errors_found = []
    
    print("🔍 Validating project files for balanced brackets, braces, and parentheses...\n")
    
    for file_path in files_to_check:
        if not file_path.exists():
            continue
            
        result = validate_file(file_path)
        
        if result['valid']:
            print(f"✓ {file_path.name}: All syntax balanced")
        else:
            all_valid = False
            errors_found.append(result)
            print(f"\n✗ {file_path.name}: Found {len(result['errors'])} error(s):")
            for err in result['errors'][:5]:  # Show first 5 errors
                section = err.get('section', '')
                if section:
                    print(f"  [{section}] {err.get('message', 'Unknown error')}")
                else:
                    print(f"  {err.get('message', 'Unknown error')}")
            
            if len(result['errors']) > 5:
                print(f"  ... and {len(result['errors']) - 5} more error(s)")
    
    print("\n" + "="*60)
    if all_valid:
        print("✅ All files validated successfully! No syntax errors found.")
        return 0
    else:
        print(f"❌ Validation failed! Found errors in {len(errors_found)} file(s).")
        print("\nPlease fix the errors before proceeding with updates.")
        return 1


if __name__ == '__main__':
    exit_code = validate_project_files()
    sys.exit(exit_code)

