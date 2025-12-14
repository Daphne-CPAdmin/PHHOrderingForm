"""
Validation function to be called before updating files.
This can be integrated into update workflows to prevent syntax errors.
"""
from validate_syntax import validate_file
from pathlib import Path


def validate_before_update(file_paths=None, fail_on_error=True):
    """
    Validate files before updating them.
    
    Args:
        file_paths: List of file paths to validate. If None, validates common project files.
        fail_on_error: If True, raises exception on validation failure. If False, returns result.
    
    Returns:
        dict with 'valid' (bool) and 'errors' (list) keys
    
    Raises:
        SyntaxError if validation fails and fail_on_error=True
    """
    if file_paths is None:
        # Default: validate main project files
        project_root = Path(__file__).parent
        file_paths = [
            project_root / 'app.py',
            project_root / 'templates' / 'index.html',
            project_root / 'templates' / 'admin.html',
        ]
    
    all_results = []
    all_valid = True
    
    for file_path in file_paths:
        file_path = Path(file_path)
        if not file_path.exists():
            continue
        
        result = validate_file(file_path)
        all_results.append(result)
        
        if not result['valid']:
            all_valid = False
            print(f"❌ {file_path.name}: {len(result['errors'])} syntax error(s) found")
            for err in result['errors'][:3]:  # Show first 3 errors
                section = err.get('section', '')
                msg = err.get('message', 'Unknown error')
                if section:
                    print(f"   [{section}] {msg}")
                else:
                    print(f"   {msg}")
        else:
            print(f"✓ {file_path.name}: Syntax validated")
    
    if not all_valid and fail_on_error:
        raise SyntaxError(f"Syntax validation failed! Found errors in {sum(1 for r in all_results if not r['valid'])} file(s). Fix errors before updating.")
    
    return {
        'valid': all_valid,
        'results': all_results,
        'errors': [err for r in all_results for err in r.get('errors', [])]
    }


if __name__ == '__main__':
    import sys
    try:
        result = validate_before_update(fail_on_error=True)
        if result['valid']:
            print("\n✅ All files validated successfully!")
            sys.exit(0)
        else:
            print("\n❌ Validation failed!")
            sys.exit(1)
    except SyntaxError as e:
        print(f"\n❌ {e}")
        sys.exit(1)

