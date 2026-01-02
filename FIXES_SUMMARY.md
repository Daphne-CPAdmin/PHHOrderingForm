# Fixes Summary - January 2, 2026

## Issues Fixed

### 1. ✅ Wrong Supplier/Price Saved to Google Sheets
**Problem:** When submitting an order for TR30 on a YIWU-only form, the system was saving the WWB supplier and WWB price to the Google Sheets instead of the correct YIWU supplier and price.

**Example:** User selects TR30 YIWU (price $10), but system saves TR30 WWB (price $12) to the order sheet.

**Root Cause:** The product lookup logic had a fallback that ignored supplier matching:

```python
# BAD - Fallback ignores supplier, returns first match by code only
if not product:
    product = next((p for p in products if p['code'].upper() == product_code.upper()), None)
```

When TR30 exists in both YIWU and WWB pricelists, this fallback would return whichever one came first in the list (typically WWB), completely ignoring which supplier the user selected.

**Solution:**
- Modified the fallback logic to ONLY work when there's exactly ONE product with that code
- If multiple products exist with the same code (from different suppliers), now returns a clear error instead of using the wrong one
- This prevents ambiguous supplier/price selection

**Fixed in 3 locations:**
1. `api_submit_order()` - Main product price lookup (line ~4424)
2. `api_submit_order()` - Vials per kit calculation (line ~4539)
3. `api_add_items()` - Order update product lookup (line ~4842)

**Files Changed:**
- `app.py` (lines 4424-4449, 4539-4543, 4842-4862)

**Expected Behavior Now:**
- ✅ TR30 YIWU selected → saves TR30 YIWU price & supplier
- ✅ TR30 WWB selected → saves TR30 WWB price & supplier
- ❌ Ambiguous match (multiple suppliers, wrong supplier requested) → returns error instead of guessing

---

### 2. ✅ Form Lock Not Preventing Order Updates
**Problem:** Users could still update their orders (via "Update Order" button) even when the form was locked. The form lock was supposed to block new submissions AND updates.

**Root Cause:** The `api_add_items()` endpoint (which handles order updates) was not checking the form lock status, unlike `api_submit_order()` which did check.

**Solution:**
- Added form lock validation to `api_add_items()` endpoint
- Now checks `get_order_form_lock()` and returns 403 error with lock message if form is locked
- Users will see the configured lock message (e.g., "Orders are currently closed. Thank you for your patience!") when attempting to update

**Files Changed:**
- `app.py` (lines 4622-4670)

**Expected Behavior:**
- ✅ Submit Order button: Disabled when locked
- ✅ Update Order button: Disabled when locked (now blocks API calls too)
- ✅ Pay Order button: Still enabled when locked (payment allowed)
- ❌ Form shows lock message when submission/update attempted

---

### 3. ✅ Live Inventory Search Not Functioning
**Problem:** The live inventory search input wasn't filtering products when users typed in the search box.

**Root Cause:** JavaScript was looking for a single element with id `'inventory-search'`, but the actual HTML uses multiple inputs with class `'inventory-search-input'` (one per supplier section) with `data-supplier` attributes.

**Solution:**
- Changed from single element lookup (`getElementById`) to multiple elements (`querySelectorAll`)
- Added proper supplier-scoped filtering: each search input now filters only its own supplier's inventory section
- Added null-safe checks for `dataset.code` and `dataset.name`

**Files Changed:**
- `templates/index.html` (lines 7371-7390)

---

## Testing Checklist

Before pushing to GitHub, verify:

### CRITICAL: Supplier/Price Data Integrity
- [ ] Create order with TR30 YIWU on YIWU form → Check Google Sheets shows YIWU supplier and YIWU price
- [ ] Create order with TR30 WWB on WWB form → Check Google Sheets shows WWB supplier and WWB price
- [ ] Check products that exist in only one supplier still work correctly
- [ ] Verify all order prices match the displayed prices (no price switching)

### Form Lock Testing
- [ ] Lock the form in admin panel
- [ ] Try to submit a NEW order → should see lock message and submission blocked
- [ ] Try to UPDATE an existing order → should see lock message and update blocked  
- [ ] Try to PAY for an order → should work (payment allowed when locked)
- [ ] Unlock the form
- [ ] Try to submit/update → should work normally

### Live Inventory Search Testing
- [ ] Navigate to customer view
- [ ] Scroll to "Live Product Inventory - YIWU" section
- [ ] Type in search box (e.g., "LEMBOT", "SP332", or partial names)
- [ ] Verify products filter correctly (matching products shown, others hidden)
- [ ] Clear search - verify all products reappear
- [ ] If multiple suppliers: test search for each supplier section independently

---

## Technical Details

### Product Lookup Logic (Fixed)

**Before (WRONG):**
```python
# Try exact match first (code + supplier)
product = find_by_code_and_supplier(product_code, supplier)

# Fallback: match by code ONLY (ignores supplier) ❌
if not product:
    product = find_by_code_only(product_code)  # Returns first match - WRONG!
```

**After (CORRECT):**
```python
# Try exact match first (code + supplier)
product = find_by_code_and_supplier(product_code, supplier)

# Fallback: ONLY if there's exactly ONE product with this code ✅
if not product:
    matching = find_all_by_code(product_code)
    if len(matching) == 1:
        product = matching[0]  # Safe - only one option
    elif len(matching) > 1:
        return ERROR  # Ambiguous - don't guess! ✅
```

### Form Lock Validation Flow
```
User clicks "Update Order"
  ↓
Frontend sends POST to /api/orders/<order_id>/add-items
  ↓
Backend checks get_order_form_lock()
  ↓
If locked: Return 403 with lock message
If unlocked: Process order update normally
```

### Inventory Search Scope
- Each supplier section has its own search input with `data-supplier` attribute
- Search filters cards within the same supplier's inventory section only
- Prevents cross-supplier filtering issues

---

## Files Modified

1. **app.py**
   - Fixed product lookup fallback logic (3 locations) to prevent wrong supplier/price
   - Added form lock check to `api_add_items()` endpoint

2. **templates/index.html**
   - Fixed inventory search to support multiple supplier-scoped search inputs

---

## Ready for Review & Deploy

All issues have been fixed and are ready for testing. No linting errors detected.

**CRITICAL TESTING:** Verify supplier/price data integrity by submitting test orders and checking Google Sheets!

**Next Steps:**
1. Run local testing following checklist above
2. **Especially test:** Submit orders with products that exist in multiple suppliers (TR30, etc.)
3. Verify Google Sheets has correct supplier and prices
4. If all tests pass, commit changes
5. Push to GitHub

**Commit Message Suggestion:**
```
Fix: Wrong supplier/price saved, form lock, and inventory search

Critical fix: Product lookup was ignoring supplier, causing wrong prices
- Fix product lookup to prevent WWB prices when YIWU selected
- Add form lock validation to order update endpoint
- Fix live inventory search for multi-supplier sections

Resolves:
- Orders now save correct supplier and prices to Google Sheets
- Users can no longer update orders when form is locked
- Inventory search now works correctly for all supplier sections
```
