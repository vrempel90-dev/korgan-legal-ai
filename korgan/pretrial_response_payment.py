from __future__ import annotations


def install_pretrial_response_payment_labels() -> None:
    """Register the new document kind in the existing payment presentation.

    This deliberately patches only the label dictionaries used by payment.py;
    payment verification, signatures and release logic stay unchanged.
    """
    from korgan import payment

    payment._KIND_RU.setdefault("pretrial_response", "ответ на претензию")
    payment._KIND_KK.setdefault("pretrial_response", "сотқа дейінгі талапқа жауап")
