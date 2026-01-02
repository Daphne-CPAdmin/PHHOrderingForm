# Fixes Summary - January 2, 2026

## Issues Fixed

### 1. ✅ Wrong Supplier/Price Saved to Google Sheets (UPDATED)
**Problem:** When submitting OR updating orders, products were being saved with the wrong supplier and price.

**Original Issue:** TR30 YIWU selected → but system saved TR30 WWB price & supplier

**NEW Issue Discovered:** When updating orders, items that WEREN'T changed were getting their supplier switched from YIWU to WWB when re-saved to Google Sheets.

**Root Causes:**
1. **Product lookup fallback ignored supplier** (lines 4424, 4539, 4842 in app.py)
2. **Frontend item loading used wrong product lookup** (line 4788 in templates/index.html)
   - When loading existing order items, code looked up products by code ONLY
   - For products in multiple suppliers (TR30 in YIWU and WWB), returned first match (usually WWB)
   - This overwrote the correct YIWU supplier stored in Google Sheets

**Solutions:**
1. Modified product lookup fallback in backend (app.py):
   - Only fallback if exactly ONE product with that code
   - If multiple products with same code → return error instead of guessing
   
2. Fixed frontend item loading logic (templates/index.html):
   - When loading existing items, preserve `item.supplier` from Google Sheets
   - Only lookup product if supplier is missing or 'Default'
   - When looking up, prefer products matching TAB_SUPPLIER (e.g., YIWU for YIWU tabs)
   - Fallback to TAB_SUPPLIER if product lookup fails

**Files Changed:**
- `app.py` (lines 4424-4449, 4539-4543, 4842-4862)
- `templates/index.html` (lines 4785-4800)

**Expected Behavior Now:**
- ✅ Submit TR30 YIWU → saves TR30 YIWU price & supplier
- ✅ Submit TR30 WWB → saves TR30 WWB price & supplier  
- ✅ Update order with TR30 YIWU + OTHER items → ALL items keep correct suppliers
- ✅ Items not changed during update → keep original supplier from Google Sheets
- ❌ Ambiguous match (wrong supplier) → returns error instead of guessing

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

Before deploying, verify:

### CRITICAL: Supplier/Price Data Integrity (UPDATED)
- [ ] **NEW CRITICAL TEST:** Update existing order with mixed items
  - Create order with TR30 YIWU + LEMBOT YIWU
  - Update order: change only TR30 quantity (leave LEMBOT unchanged)
  - Check Google Sheets: BOTH TR30 and LEMBOT should still be YIWU
- [ ] Create order with TR30 YIWU on YIWU form → Check Sheets shows YIWU supplier and price
- [ ] Create order with TR30 WWB on WWB form → Check Sheets shows WWB supplier and price
- [ ] Update order: add new YIWU item → Check new item has YIWU supplier
- [ ] Update order: remove item → Check remaining items keep correct suppliers
- [ ] Verify products in only one supplier still work correctly

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
- [ ] Type in search box (e.g., "LEMBOT", "TR30")
- [ ] Verify products filter correctly
- [ ] Clear search - verify all products reappear
- [ ] If multiple suppliers: test each section independently

---

## Technical Details

### Product Lookup Logic (Fixed - 2 Locations)

**Backend (app.py) - Before (WRONG):**
```python
# Try exact match first (code + supplier)
product = find_by_code_and_supplier(product_code, supplier)

# Fallback: match by code ONLY (ignores supplier) ❌
if not product:
    product = find_by_code_only(product_code)  # Returns first match - WRONG!
```

**Backend (app.py) - After (CORRECT):**
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

**Frontend (index.html) - Before (WRONG):**
```javascript
// Get supplier from item or lookup by code only
let itemSupplier = item.supplier || 'Default';
if (!itemSupplier || itemSupplier === 'Default') {
    const product = allProducts?.find(p => p.code === item.product_code);  // ❌ Code only!
    itemSupplier = product?.supplier || 'Default';
}
```

**Frontend (index.html) - After (CORRECT):**
```javascript
// Preserve supplier from Google Sheets, prefer TAB_SUPPLIER when looking up
let itemSupplier = item.supplier || 'Default';  // ✅ Keep original supplier
if (!itemSupplier || itemSupplier === 'Default') {
    // Only lookup if missing - prefer matching TAB_SUPPLIER first
    let product = allProducts?.find(p => 
        p.code === item.product_code && 
        p.supplier === TAB_SUPPLIER  // ✅ Match supplier too!
    );
    if (!product) {
        product = allProducts?.find(p => p.code === item.product_code);
    }
    itemSupplier = product?.supplier || TAB_SUPPLIER || 'Default';
}
```

---

## Commits

1. **ad44ea1** - "Fix: Wrong supplier/price saved, form lock, and inventory search"
   - Initial fixes for backend product lookup, form lock, inventory search

2. **4d6152e** - "Fix: Preserve correct supplier when loading existing order items"
   - Additional fix for frontend item loading to prevent supplier switching during updates

---

## Ready for Deploy

All issues fixed and pushed to GitHub. **CRITICAL:** Test the updated order scenario where unchanged items were switching suppliers.

**Test Priority:**
1. 🔴 **CRITICAL:** Update order test (mixed items, change only some)
2. 🟡 **HIGH:** New order submission (YIWU vs WWB)
3. 🟢 **MEDIUM:** Form lock enforcement
4. 🟢 **MEDIUM:** Inventory search

**Deployment Notes:**
- Two commits pushed
- All linting checks pass
- No breaking changes to API or database schema
- Backward compatible with existing orders
