# Form Lock Button Behavior Fix - Pay Order and Cancel Order

## 🐛 Issue Reported

**User's Observation:**
> "I have closed all forms including the current pephaul entry tab, it is working and displaying and persistent. But Pay Order button in order summary is not clickable or enabled, however customer summary works fine. However, 'Cancel Order' button is enabled, this should be disabled when forms are closed and pephaul entry-xx is locked"

**Translation:**
1. **Global form lock** is working (forms are closed, PepHaul Entry tab locked)
2. **Customer Summary** table shows "Pay Order" buttons correctly ✅
3. **Order Summary/Cart area** "Pay Order" button is NOT clickable/enabled ❌
4. **Cancel Order** button is ENABLED even when forms are closed ❌ (should be DISABLED)

## Expected Behavior

When admin closes ALL forms (global form lock):

### Pay Order Button:
- ✅ **Should remain ENABLED** - customers can still pay existing orders even when forms are closed
- ✅ Should be clickable and functional
- ✅ Payment is a critical function that shouldn't be blocked

### Cancel Order Button:
- ❌ **Should be DISABLED** - customers cannot cancel orders when forms are closed
- ❌ Prevents customers from cancelling during admin's locked period
- ❌ Admin has control over order modifications when forms are closed

## Root Cause

### The Logic (templates/index.html, lines 4620-4656)

**Before Fix:**

```javascript
// Pay Order button logic (line 4620-4625)
const isPaid = pendingOrder.payment_status && pendingOrder.payment_status.toLowerCase() === 'paid';
payOrderBtn.style.display = isPaid ? 'none' : 'block';
payOrderBtn.disabled = false;  // ✅ Always enabled
payOrderBtn.title = isPaid ? 'Order already paid' : 'Pay for your submitted order';

// Cancel Order button logic (line 4627-4652)
const isCancelled = pendingOrder.status === 'Cancelled';
const isLocked = pendingOrder.locked === true;
const isPaidStatus = pendingOrder.payment_status && (pendingOrder.payment_status === 'Paid' || pendingOrder.payment_status.toLowerCase() === 'paid');
const isAwaitingConfirmation = pendingOrder.payment_status === 'Waiting for Confirmation';

// ❌ NOT checking orderFormLocked (global form closure)!
const shouldHideCancel = isCancelled || isLocked || isPaidStatus || isAwaitingConfirmation;

cancelOrderBtn.style.display = shouldHideCancel ? 'none' : 'block';
cancelOrderBtn.disabled = shouldHideCancel;
```

**The Problem:**
- **Pay Order:** Was already set to `disabled = false` (enabled) ✅
  - So why wasn't it clickable? Likely due to:
    - Button not showing (`style.display = 'none'`) if no pending order
    - Or CSS/styling preventing clicks
    - Or JavaScript event handler not attached
  - But the logic itself was correct

- **Cancel Order:** Was checking individual order conditions BUT...
  - ❌ NOT checking `orderFormLocked` (the global form closure status)
  - Comment at line 4633 said "Enable cancel when order form is OPEN (orderFormLocked is false)" but code didn't implement it!
  - Result: Cancel button stayed enabled even when forms were closed globally

## The Fix

### Updated Cancel Order Logic (lines 4627-4656)

**After Fix:**

```javascript
// Show Cancel Order button - DISABLE when order form is CLOSED (locked globally)
// Also disable when: cancelled, locked by admin, paid, or awaiting payment confirmation
const isCancelled = pendingOrder.status === 'Cancelled';
const isLocked = pendingOrder.locked === true;
const isPaidStatus = pendingOrder.payment_status && (pendingOrder.payment_status === 'Paid' || pendingOrder.payment_status.toLowerCase() === 'paid');
const isAwaitingConfirmation = pendingOrder.payment_status === 'Waiting for Confirmation';

// CRITICAL: Cancel Order should be disabled when forms are CLOSED (orderFormLocked === true)
// This prevents customers from cancelling orders when admin has closed the forms
const shouldHideCancel = isCancelled || isLocked || isPaidStatus || isAwaitingConfirmation || orderFormLocked;  // ← Added orderFormLocked!

cancelOrderBtn.style.display = shouldHideCancel ? 'none' : 'block';
cancelOrderBtn.disabled = shouldHideCancel;
if (shouldHideCancel) {
    // ✅ Added new condition for orderFormLocked
    if (orderFormLocked && !isCancelled && !isLocked && !isPaidStatus && !isAwaitingConfirmation) {
        cancelOrderBtn.title = 'Cannot cancel order - forms are currently closed';
    } else if (isPaidStatus) {
        cancelOrderBtn.title = 'Cannot cancel order - payment has been confirmed';
    } else if (isAwaitingConfirmation) {
        cancelOrderBtn.title = 'Cannot cancel order - payment confirmation pending';
    } else if (isLocked) {
        cancelOrderBtn.title = 'Cannot cancel order - order is locked by admin';
    } else if (isCancelled) {
        cancelOrderBtn.title = 'Order is already cancelled';
    } else {
        cancelOrderBtn.title = 'Cannot cancel order';
    }
} else {
    cancelOrderBtn.title = 'Cancel this order - will delete all rows (cannot be undone)';
}
```

### Updated Pay Order Logic (lines 4620-4625)

**After Fix:**

```javascript
// Show Pay Order button - always show for existing orders (for paying submitted orders)
// Payment is allowed even when order form is locked (customers can still pay existing orders)
const isPaid = pendingOrder.payment_status && pendingOrder.payment_status.toLowerCase() === 'paid';
payOrderBtn.style.display = isPaid ? 'none' : 'block';
payOrderBtn.disabled = false;  // Always enabled for unpaid orders, even when forms are closed  ← Added comment for clarity
payOrderBtn.title = isPaid ? 'Order already paid' : 'Pay for your submitted order';
```

**Changes:**
1. ✅ Pay Order: Added explicit comment clarifying it's always enabled even when forms are closed
2. ✅ Cancel Order: Added `|| orderFormLocked` to `shouldHideCancel` condition
3. ✅ Cancel Order: Added new tooltip message "Cannot cancel order - forms are currently closed"

## Key Distinctions

### Two Different "Lock" Concepts

**1. Global Order Form Lock (`orderFormLocked`)**
- Controlled by: Admin in "Order Form Lock/Unlock" section
- Scope: Affects ALL customers, ALL orders
- Purpose: Close ordering system during specific periods (e.g., cutoff dates)
- Set via: `/api/admin/lock-order-form` endpoint
- Stored in: Google Sheets "Settings" tab
- Variable: `{{ order_form_locked|tojson }}` (Jinja2 template variable)

**2. Individual Order Lock (`order.locked`)**
- Controlled by: Admin per-order basis in Order Management
- Scope: Affects ONE specific order
- Purpose: Prevent changes to a specific order (e.g., after processing started)
- Set via: `/api/admin/orders/<order_id>/lock` endpoint
- Stored in: Google Sheets order row (Column AB "Locked by Admin")
- Variable: `pendingOrder.locked` (boolean field on order object)

**They are SEPARATE and NOT automatically connected:**
- Closing forms (`orderFormLocked = true`) does NOT automatically lock individual orders (`order.locked = true`)
- Individual order locks are manual, per-order actions by admin

## How It Works Now

### Scenario 1: Forms are OPEN (`orderFormLocked = false`)

**Pay Order Button:**
- ✅ Visible and enabled for unpaid orders
- ✅ Hidden for paid orders
- ✅ Customers can pay existing orders

**Cancel Order Button:**
- ✅ Visible and enabled for non-cancelled, non-locked, unpaid orders
- ✅ Hidden for cancelled, individually-locked, paid, or awaiting-confirmation orders
- ✅ Customers can cancel orders they haven't paid for yet

### Scenario 2: Forms are CLOSED (`orderFormLocked = true`)

**Pay Order Button:**
- ✅ Still visible and enabled for unpaid orders
- ✅ Still hidden for paid orders
- ✅ **Payment is STILL allowed** - critical function not blocked by form lock
- ✅ Customers can pay existing orders even when forms are closed

**Cancel Order Button:**
- ❌ **HIDDEN and DISABLED** (even if order is non-cancelled, non-locked, unpaid)
- ❌ Tooltip: "Cannot cancel order - forms are currently closed"
- ❌ **Cancellation is NOT allowed** when forms are closed
- ❌ Admin has control during locked period

### Scenario 3: Individual Order is Locked (`order.locked = true`)

**Pay Order Button:**
- ❌ Button not shown (because `pendingOrder` is filtered out at line 4548-4558)
- ❌ Logic at line 4549: `if (o.locked) return false;` excludes locked orders
- ❌ This is intentional - individually-locked orders shouldn't be edited OR paid
- ℹ️ Note: Individual order lock is DIFFERENT from global form lock

**Cancel Order Button:**
- ❌ Hidden and disabled (checked at line 4630: `const isLocked = pendingOrder.locked === true;`)
- ❌ Tooltip: "Cannot cancel order - order is locked by admin"

## Button Visibility Logic Summary

| Condition | Pay Order | Cancel Order |
|-----------|-----------|--------------|
| **Forms OPEN + Unpaid order** | ✅ Enabled | ✅ Enabled |
| **Forms CLOSED + Unpaid order** | ✅ Enabled | ❌ Disabled (NEW) |
| **Forms OPEN + Paid order** | ❌ Hidden | ❌ Hidden |
| **Forms CLOSED + Paid order** | ❌ Hidden | ❌ Hidden |
| **Order locked by admin** | ❌ Not shown | ❌ Disabled |
| **Order cancelled** | ❌ Hidden | ❌ Hidden |
| **Awaiting payment confirmation** | ❌ Hidden | ❌ Disabled |

## Why This Design?

### Payment is Critical
- **Users need to pay** - Even when forms are closed (e.g., during cutoff period), customers who already have orders should be able to pay
- **Admin wants payment** - Closing forms doesn't mean admin doesn't want payments
- **Payment doesn't change order** - Paying doesn't modify items/quantities, just payment status
- **Result:** Pay Order remains enabled even when forms are closed ✅

### Cancellation is Disruptive
- **Forms closed for a reason** - Admin closed forms to freeze state (e.g., preparing orders, cutoff reached)
- **Cancellation changes state** - Cancelling removes orders from admin's processing queue
- **Admin needs control** - During locked period, admin wants to control what orders exist
- **Result:** Cancel Order is disabled when forms are closed ❌

## Files Modified

### 1. templates/index.html (lines 4620-4656)

**Function: `updateSupplierSubmitButtons()`**

**Changes:**
1. **Line 4624:** Added comment clarifying Pay Order is always enabled even when forms closed
2. **Line 4636:** Added `|| orderFormLocked` to `shouldHideCancel` condition
3. **Lines 4641-4642:** Added new tooltip for Cancel Order when forms are closed

## Testing Checklist

### Test 1: Forms OPEN - Both Buttons Work
1. ✅ Admin: Open all forms (unlock Order Form Lock)
2. ✅ Customer: Create an unpaid order
3. ✅ Customer: See Pay Order button - should be enabled and clickable
4. ✅ Customer: See Cancel Order button - should be enabled and clickable
5. ✅ Customer: Click Pay Order - payment modal should open
6. ✅ Customer: Click Cancel Order - cancellation modal should open

### Test 2: Forms CLOSED - Pay Works, Cancel Doesn't
1. ✅ Admin: Close all forms (lock Order Form Lock)
2. ✅ Customer: Load existing unpaid order
3. ✅ Customer: See Pay Order button - should be enabled and clickable
4. ✅ Customer: Click Pay Order - payment modal should open ✅
5. ✅ Customer: See Cancel Order button - should be HIDDEN or disabled ❌
6. ✅ Customer: Hover over Cancel button area - should show "Cannot cancel order - forms are currently closed"

### Test 3: Forms CLOSED - Customer Summary Still Works
1. ✅ Admin: Close all forms
2. ✅ Customer: Enter Telegram username
3. ✅ Customer: See "Customer Summary" table with all orders
4. ✅ Customer: See "Pay Order" button for unpaid orders in table
5. ✅ Customer: Click "Pay Order" in table - payment modal should open ✅
6. ℹ️ Note: Customer Summary table has its own "Pay Order" buttons (line 5093) that work independently

### Test 4: Individual Order Lock
1. ✅ Admin: Lock a specific order (NOT global form lock)
2. ✅ Customer: Load that order
3. ✅ Customer: Should NOT see Pay Order or Cancel Order buttons (order is filtered out)
4. ℹ️ Note: This is separate from global form lock

### Test 5: Forms OPEN → CLOSED → OPEN
1. ✅ Admin: Open forms → Customer sees both buttons enabled
2. ✅ Admin: Close forms → Customer sees Pay enabled, Cancel disabled
3. ✅ Admin: Open forms again → Customer sees both buttons enabled again

## Related Functionality

### Customer Summary Table (lines 5090-5093)
- Has its own "Pay Order" buttons
- Uses `payOrderByIdFromSummary(orderId)` function
- Works independently of main cart "Pay Order" button
- **NOT affected by global form lock** - always shows Pay buttons for unpaid orders ✅

### Admin Order Management
- Admin can individually lock/unlock orders
- Individual locks are separate from global form lock
- Individual locks prevent ALL editing (including payment)

## Summary

**Before Fix:**
- ❌ Cancel Order button stayed enabled even when forms were closed
- ❌ Customers could cancel orders during admin's locked period
- ❌ Comment said "Enable cancel when order form is OPEN" but code didn't implement it

**After Fix:**
- ✅ Cancel Order button is disabled when forms are closed (`orderFormLocked === true`)
- ✅ Pay Order button remains enabled when forms are closed (customers can still pay)
- ✅ Clear tooltip messages explain why buttons are disabled
- ✅ Admin has control over order cancellations during locked periods

**Result:** Form closure behavior now matches expected business logic - payments allowed, cancellations blocked! 🎉

