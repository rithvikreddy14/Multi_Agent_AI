# app/core/bot_templates.py
"""
All WhatsApp message templates for the Nexus support bot.

Rules:
  - No message exceeds 3 short paragraphs (WhatsApp is a chat app, not email).
  - Every message that expects a reply offers numbered options OR an explicit prompt.
  - Templates are pure functions — no side effects, no DB calls.
  - Variable names use {snake_case} placeholders filled at call time.
"""

# ─────────────────────────────────────────────────────────────────────────────
# GREETING TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────

def tmpl_greeting_active(order_id: str, item: str, restaurant: str) -> str:
    return (
        f"Hi! 👋 Welcome to Nexus Support.\n\n"
        f"I found your active order:\n"
        f"📦 {order_id} — {item} from {restaurant}\n\n"
        f"What can I help you with?\n"
        f"1️⃣ Track my order\n"
        f"2️⃣ Report a problem\n"
        f"3️⃣ Speak to support"
    )


def tmpl_greeting_no_order() -> str:
    return (
        "Hi! 👋 Welcome to Nexus Support.\n\n"
        "I don't see any active orders right now.\n\n"
        "What can I help with?\n"
        "1️⃣ Report a problem with a past order\n"
        "2️⃣ Check my order history\n"
        "3️⃣ Speak to support"
    )


def tmpl_greeting_multi_order(order_list: str) -> str:
    """order_list: pre-formatted string of numbered orders, e.g. '1️⃣ ORD-4521...'"""
    return (
        f"Hi! 👋 I found multiple active orders. Which one can I help with?\n\n"
        f"{order_list}\n\n"
        f"Reply with the number of your order."
    )


def tmpl_greeting_timeout_return(order_id: str, item: str, restaurant: str) -> str:
    """Shown when a session has expired and the user sends a new message."""
    return (
        f"Welcome back! 👋 Our previous chat timed out, so let's start fresh.\n\n"
        f"Your active order: 📦 {order_id} — {item} from {restaurant}\n\n"
        f"1️⃣ Track my order\n"
        f"2️⃣ Report a problem\n"
        f"3️⃣ Speak to support"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TRACKING TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────

def tmpl_tracking_on_the_way(courier: str, eta: int, progress: int) -> str:
    return (
        f"📍 Your order is on the way!\n\n"
        f"🛵 Courier: {courier}\n"
        f"⏱ ETA: {eta} minutes\n"
        f"📊 Progress: {progress}% of route complete\n\n"
        f"Need anything else?\n"
        f"1️⃣ Report a problem with this order\n"
        f"2️⃣ Talk to support\n"
        f"3️⃣ That's all, thanks"
    )


def tmpl_tracking_preparing(restaurant: str, pickup_eta: int) -> str:
    return (
        f"👨‍🍳 Your order is being prepared at {restaurant}!\n\n"
        f"Estimated courier pickup: ~{pickup_eta} minutes\n\n"
        f"I'll update you once it's picked up. 🛵\n\n"
        f"1️⃣ Report a problem\n"
        f"2️⃣ That's all, thanks"
    )


def tmpl_tracking_delivered(delivered_time: str) -> str:
    return (
        f"✅ Your order was marked as delivered at {delivered_time}.\n\n"
        f"Enjoy your meal! 🍽\n\n"
        f"1️⃣ Report a problem with this order\n"
        f"2️⃣ Rate my experience\n"
        f"3️⃣ That's all"
    )


def tmpl_tracking_delayed(new_eta: int, delay_minutes: int) -> str:
    return (
        f"⏰ Your order is running about {delay_minutes} minutes late — sorry!\n\n"
        f"Updated ETA: ~{new_eta} minutes\n\n"
        f"As a goodwill gesture, use *DELAY10* for 10% off your next order. 🎟\n\n"
        f"1️⃣ Report a problem\n"
        f"2️⃣ That's all, thanks"
    )


# ─────────────────────────────────────────────────────────────────────────────
# COMPLAINT — ORDER SELECTION
# ─────────────────────────────────────────────────────────────────────────────

def tmpl_complaint_select_order(order_list: str) -> str:
    return (
        f"I'm sorry to hear that! Let me help. 🙏\n\n"
        f"Which order has the problem?\n\n"
        f"{order_list}\n\n"
        f"Reply with the number, or type the order ID directly."
    )


# ─────────────────────────────────────────────────────────────────────────────
# COMPLAINT — ISSUE TYPE SELECTION
# ─────────────────────────────────────────────────────────────────────────────

def tmpl_complaint_issue_menu(order_id: str, item: str) -> str:
    return (
        f"Got it — {order_id}, {item}.\n\n"
        f"What's the issue?\n"
        f"1️⃣ 🚫 Missing item\n"
        f"2️⃣ ❌ Wrong order delivered\n"
        f"3️⃣ 🤢 Bad quality / spoilage\n"
        f"4️⃣ ⏰ Late delivery\n"
        f"5️⃣ 📦 Quantity short\n"
        f"6️⃣ 💔 Packaging damaged\n"
        f"7️⃣ 🔄 Other"
    )


# ─────────────────────────────────────────────────────────────────────────────
# COMPLAINT — IMAGE STEP
# ─────────────────────────────────────────────────────────────────────────────

def tmpl_image_request(issue_type: str) -> str:
    """Tailored prompt depending on what kind of issue was reported."""
    guidance = {
        "missing_item":       "the items you received — show the full container",
        "wrong_order":        "the food / label you received — clearly show what it is",
        "spoilage":           "the damaged or spoiled food — show the condition clearly",
        "quantity_short":     "all the items received in the same frame",
        "packaging_damaged":  "the damaged packaging — show the tear or crush",
    }
    hint = guidance.get(issue_type, "what you received — show the packaging and food")
    return (
        f"Understood. 😔 To process your claim I need a photo.\n\n"
        f"📸 Please send a clear photo showing: {hint}\n\n"
        f"Take the photo *now* from your camera (not from your gallery)."
    )


def tmpl_image_invalid_no_exif() -> str:
    return (
        "I couldn't verify that photo. 🤔\n\n"
        "It looks like it may have been taken from your gallery or is a screenshot.\n\n"
        "Please take a *fresh photo now* from your camera and send it. 📸"
    )


def tmpl_image_invalid_duplicate() -> str:
    return (
        "⚠️ This image has been used in a previous support request.\n\n"
        "Please take a *new photo* of your current order and send it. 📸"
    )


def tmpl_image_invalid_format() -> str:
    return (
        "I can only accept JPEG or PNG photos. 📸\n\n"
        "Please send a regular photo from your camera (not a document or video)."
    )


def tmpl_image_invalid_size() -> str:
    return (
        "That photo is too large to process (max 10 MB). 😅\n\n"
        "Please compress it slightly or take a new one with standard camera settings."
    )


def tmpl_image_received() -> str:
    return (
        "✅ Photo received!\n\n"
        "Now briefly describe the problem in one or two sentences."
    )


# ─────────────────────────────────────────────────────────────────────────────
# COMPLAINT — LATE DELIVERY (no image needed)
# ─────────────────────────────────────────────────────────────────────────────

def tmpl_late_delivery_request() -> str:
    return (
        "Late delivery — I completely understand the frustration. ⏰\n\n"
        "How late was it, and has your order arrived?\n\n"
        "1️⃣ It arrived but was very late\n"
        "2️⃣ Still waiting — it hasn't arrived yet\n"
        "3️⃣ The order never came"
    )


def tmpl_late_arrived_coupon(coupon_code: str, delay_minutes: int) -> str:
    return (
        f"Sorry about the {delay_minutes}-minute delay! ⏰\n\n"
        f"As an apology:\n"
        f"🎟 *{coupon_code}* — 15% off your next order\n"
        f"📅 Valid for 14 days\n\n"
        f"Does this resolve your issue?\n"
        f"1️⃣ Yes, thanks!\n"
        f"2️⃣ No, I need more help"
    )


def tmpl_still_waiting_track(courier: str, eta: int) -> str:
    return (
        f"Let me check on that for you.\n\n"
        f"🛵 Courier: {courier} is still on the way\n"
        f"⏱ Updated ETA: {eta} minutes\n\n"
        f"1️⃣ Report a problem\n"
        f"2️⃣ Speak to support"
    )


def tmpl_order_never_arrived() -> str:
    return (
        "That's a serious issue — I'm escalating this immediately. 🚨\n\n"
        "Our team will:\n"
        "• Review the courier's delivery proof and GPS data\n"
        "• Contact the courier if needed\n\n"
        "You'll receive a response within 15 minutes. 🙏"
    )


# ─────────────────────────────────────────────────────────────────────────────
# FRAUD CHECK — PROCESSING
# ─────────────────────────────────────────────────────────────────────────────

def tmpl_processing() -> str:
    return "Thanks — analysing your claim now... ⏳"


# ─────────────────────────────────────────────────────────────────────────────
# RESOLUTION TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────

def tmpl_resolution_coupon(coupon_code: str, discount_pct: int, valid_days: int) -> str:
    return (
        f"✅ Your claim has been verified!\n\n"
        f"I'm sorry about the issue. Here's your compensation:\n"
        f"🎟 *{coupon_code}*\n"
        f"💰 {discount_pct}% off your next order\n"
        f"📅 Valid for {valid_days} days\n\n"
        f"Does this resolve your issue?\n"
        f"1️⃣ Yes, thanks! 😊\n"
        f"2️⃣ No, I'd like more help"
    )


def tmpl_resolution_denied() -> str:
    return (
        "We've carefully reviewed your request.\n\n"
        "Unfortunately, we're unable to process an automated refund for this claim at this time.\n\n"
        "1️⃣ Speak to our support team\n"
        "2️⃣ Submit additional evidence\n"
        "3️⃣ Raise a complaint through the app"
    )


def tmpl_resolution_manual_review(case_id: str) -> str:
    return (
        f"Your claim has been sent to our review team. 🔍\n\n"
        f"📋 Case ID: {case_id}\n"
        f"⏱ We'll respond within 24 hours\n\n"
        f"We'll message you here once it's resolved. 🙏"
    )


def tmpl_resolution_escalate(case_id: str, agent_name: str, eta_minutes: int) -> str:
    return (
        f"Connecting you to our support team now. 🙏\n\n"
        f"📋 Case ID: {case_id}\n"
        f"👤 Agent: {agent_name}\n"
        f"⏱ Typical reply: ~{eta_minutes} minutes\n\n"
        f"The bot is paused. Type *menu* anytime to restart."
    )


def tmpl_resolution_satisfied() -> str:
    return (
        "Wonderful! 🎉 Glad we could sort that out.\n\n"
        "⭐ How was your support experience today?\n"
        "1️⃣ 😊 Great\n"
        "2️⃣ 😐 Okay\n"
        "3️⃣ 😞 Could be better"
    )


def tmpl_rating_thanks(rating: int) -> str:
    messages = {
        1: "Thank you! We're glad we could help. 😊 Have a great day!",
        2: "Thanks for the feedback! We'll keep improving. 🙏",
        3: "Sorry we didn't meet your expectations. Your feedback helps us get better. 🙏",
    }
    return messages.get(rating, "Thanks for the feedback! 🙏")


# ─────────────────────────────────────────────────────────────────────────────
# ALREADY REFUNDED
# ─────────────────────────────────────────────────────────────────────────────

def tmpl_already_refunded(order_id: str, refund_date: str, amount: str) -> str:
    return (
        f"It looks like {order_id} already has a resolved claim. ✅\n\n"
        f"Refund of {amount} was processed on {refund_date}.\n\n"
        f"Is there a different order you need help with?\n"
        f"1️⃣ Yes — different order\n"
        f"2️⃣ I haven't received the refund yet\n"
        f"3️⃣ Speak to support"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLAIM OUT OF WINDOW
# ─────────────────────────────────────────────────────────────────────────────

def tmpl_out_of_window(hours_since_delivery: float) -> str:
    return (
        f"This order was delivered {hours_since_delivery:.0f} hours ago. ⏰\n\n"
        f"Refund claims must be raised within 2 hours of delivery.\n\n"
        f"1️⃣ Speak to support for an exception\n"
        f"2️⃣ That's understood, thanks"
    )


# ─────────────────────────────────────────────────────────────────────────────
# EDGE CASE / ERROR TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────

ERR_UNKNOWN = (
    "I didn't quite catch that. 😅\n\n"
    "Here's what I can help with:\n"
    "1️⃣ Track my order\n"
    "2️⃣ Report a problem\n"
    "3️⃣ Speak to support"
)

ERR_VOICE_NOTE = (
    "I received your voice message, but I can't process audio yet! 😅\n\n"
    "Please type your issue or choose an option:\n"
    "1️⃣ Track my order\n"
    "2️⃣ Report a problem\n"
    "3️⃣ Speak to support"
)

ERR_VIDEO = (
    "I received a video, but I can only process photos right now. 📸\n\n"
    "Please send a photo of the issue instead."
)

ERR_ORDER_NOT_FOUND = (
    "I couldn't find that order. 🤔\n\n"
    "Please double-check the order ID, or:\n"
    "1️⃣ See my recent orders\n"
    "2️⃣ Speak to support"
)

ERR_TOO_MANY_RETRIES = (
    "Looks like we're going in circles! 😅 Let me reset and start fresh.\n\n"
    "What can I help you with?\n"
    "1️⃣ Track my order\n"
    "2️⃣ Report a problem\n"
    "3️⃣ Speak to support"
)

ERR_PLEASE_REPLY_NUMBER = (
    "Please reply with one of the numbered options shown above. 👆"
)


# ─────────────────────────────────────────────────────────────────────────────
# PROACTIVE NOTIFICATIONS (outbound, not triggered by user)
# ─────────────────────────────────────────────────────────────────────────────

def notif_order_picked_up(item: str, courier: str, eta: int) -> str:
    return (
        f"🛵 Your {item} has been picked up!\n\n"
        f"Courier: {courier}\n"
        f"ETA: ~{eta} minutes\n\n"
        f"Reply *track* anytime for a live update."
    )


def notif_order_delivered(item: str, delivered_time: str) -> str:
    return (
        f"✅ Your {item} was just delivered! ({delivered_time})\n\n"
        f"Enjoy your meal! 🍽\n\n"
        f"Any issues? Reply *problem* and I'll help."
    )


def notif_order_delayed(item: str, delay_minutes: int, new_eta: int) -> str:
    return (
        f"⏰ Heads up — your {item} is running about {delay_minutes} minutes late.\n\n"
        f"New ETA: ~{new_eta} minutes. Sorry for the wait!\n\n"
        f"Reply *track* for a live update."
    )

def tmpl_complaint_select_item(items_text: str) -> str:
    return (
        f"Which specific item was missing or incorrect?\n\n"
        f"{items_text}\n\n"
        f"Please reply with the corresponding number."
    )