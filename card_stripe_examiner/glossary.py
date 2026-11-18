"""Definitions for the fields this program reads. No encoding guidance."""

from __future__ import annotations

GLOSSARY: list[dict[str, str]] = [
    {
        "title": "Sentinels and separators",
        "body": (
            "A keyboard-wedge reader types each track with a start character and an end character. "
            "Track 1 starts with %, track 2 starts with ;, and track 3 starts with +. "
            "Each track ends with ?. Track 1 separates the account, the name, and the rest of the data with ^. "
            "Track 2 separates the account from the rest of the data with =. "
            "Some readers type D in that position instead of =. "
            "If a track was not on the stripe, the reader usually omits it."
        ),
    },
    {
        "title": "PAN and IIN",
        "body": (
            "The primary account number, often called the PAN, is the account printed for a bank card. "
            "The first digits are the issuer identification number, still often called the BIN. "
            "Older ranges use 6 digits. Many current ranges use 8. "
            "Those leading digits identify the network and, when a directory has them, the issuing institution. "
            "They are not the whole account. This program's bank lookup transmits only those 6 or 8 digits."
        ),
    },
    {
        "title": "Cardholder name",
        "body": (
            "Track 1 can carry the name in a fixed field between ^ characters. "
            "The usual order on the stripe is surname, a slash, then the given name. "
            "The summary shows a readable order and the spelling that was on the stripe. "
            "Track 2 does not carry the name. A missing name does not, by itself, describe how the stripe was written."
        ),
    },
    {
        "title": "Expiration",
        "body": (
            "On a bank-format stripe the expiration is four digits, year then month, called YYMM. "
            "This program shows that as MM/20YY and treats the card as expired only after that month has ended. "
            "If those four characters are not a real month, they are not presented as a date. "
            "Closed-loop gift cards often put other numbers in that position."
        ),
    },
    {
        "title": "Service code",
        "body": (
            "A bank-format stripe carries a three-digit service code after the expiration. "
            "The first digit describes interchange and whether a chip is preferred where a terminal supports one. "
            "The second digit describes how authorization is performed. "
            "The third digit describes the services allowed and whether a PIN is part of that use. "
            "The summary writes those three positions out next to the digits. "
            "A difference between track 1 and track 2 is reported as a difference, not as a conclusion."
        ),
    },
    {
        "title": "Discretionary data",
        "body": (
            "The characters after the service code are discretionary data. "
            "The issuer defines that field. It can include issuer verification data. "
            "The meaning changes by institution, so this program shows the characters and labels them issuer-defined. "
            "It does not calculate verification values."
        ),
    },
    {
        "title": "Luhn check",
        "body": (
            "The Luhn check is a public checksum on an account number. "
            "A pass means the last digit matches that checksum. A fail means it does not. "
            "The check does not authorize a transaction, identify a person, or show that an account was issued. "
            "It is a way to see whether the digits read from the stripe are internally consistent."
        ),
    },
    {
        "title": "Track 3",
        "body": (
            "Track 3 is the thrift track. Many current credit and debit cards do not carry it. "
            "When the digits match the ISO 4909 layout, this program reads the format code, the account, "
            "and the country and currency positions. Anything else on that track is shown as additional data. "
            "If the layout does not match, the raw track is kept and marked unrecognized. "
            "Presence of track 3 is noted because it is uncommon on many bank cards."
        ),
    },
    {
        "title": "Gift and prepaid cards",
        "body": (
            "A network prepaid card often uses the same bank-format tracks as a credit or debit card. "
            "Those reads are labeled bank format. "
            "A closed-loop gift card is often track 2 only, or it uses a private layout that does not contain "
            "a standard expiration and service code. Those reads are labeled non-standard or proprietary. "
            "The raw characters are still kept, and a Luhn check is run when a long account number is present."
        ),
    },
    {
        "title": "BIN lookup",
        "body": (
            "The issuing-bank name comes from binlist.net, a public directory. "
            "The request sends only the first 8 digits of the account, or the first 6 if the 8-digit prefix is not listed. "
            "The account number, name, expiration, discretionary data, tracks, case number, and examiner name are not sent. "
            "The examiner starts the lookup. A swipe does not. "
            "The directory can be incomplete, and a bank name from it is not a verification by the issuer."
        ),
    },
    {
        "title": "What a difference means",
        "body": (
            "This program compares the account, expiration, and service code on track 1 with the same fields on track 2. "
            "It also notes an expired date, a missing track 1 or track 2, and a track 3 that was read. "
            "Those are facts about the swipe in front of the examiner. "
            "They are not a determination that a stripe was copied or altered."
        ),
    },
    {
        "title": "Printed card",
        "body": (
            "The reader cannot see the plastic. If the account number, name, and expiration printed on the card "
            "all match the stripe, tick the box that says so. Otherwise, type what is printed and the program "
            "compares each entry with the stripe: the account number digit for digit, the expiration as month and year "
            "(12/28, 12/2028 and 1228 are read the same), and the name word by word, ignoring order, punctuation "
            "and titles such as MR. A field left blank is not compared. "
            "A difference is the examiner's observation of the plastic against the swipe. "
            "It is not a determination that the card is fraudulent."
        ),
    },
    {
        "title": "Read errors",
        "body": (
            "When the reader cannot read a track it types E in place of the data, for example %E? or ;E?. "
            "The program lists that track as a read error, not as a track that was read, and asks for another swipe. "
            "A swipe in which every track failed is not added to the case. "
            "Read errors usually come from a fast or uneven swipe, a worn stripe, or dirt on the reader head."
        ),
    },
    {
        "title": "Account length",
        "body": (
            "Each network issues accounts of particular lengths, for example 15 digits for American Express "
            "and 16 for Mastercard. The network is inferred from the leading digits. "
            "When the length does not fit that network, the program adds a finding. "
            "The inference is from the prefix only; it does not prove which network issued the card."
        ),
    },
    {
        "title": "Exhibit number",
        "body": (
            "Each card is given the next exhibit number when it is swiped, using the prefix and starting "
            "number chosen for the case. The number can be changed on the Summary tab so it matches the "
            "evidence label on the item."
        ),
    },
    {
        "title": "Card type",
        "body": (
            "Record what the plastic is: a bank card, gift card, hotel key, ID or membership card, or blank plastic. "
            "A bank-format stripe on a card that is not printed as a bank card is reported as a finding, "
            "and so is a card printed as a bank card that does not carry a bank-format stripe."
        ),
    },
    {
        "title": "Same account on more than one card",
        "body": (
            "The program compares the account numbers on every track of every card in the case. "
            "Cards that share an account number are listed against each other. "
            "Cards with identical stripe data are reported separately, because that can also mean the same card was swiped twice."
        ),
    },
    {
        "title": "Where cases are saved",
        "body": (
            "Save puts each case in its own folder, named by case number, under AppData\\Local\\CardStripeExaminer\\Cases "
            "in your Windows profile. The folder holds the case file and a Photos folder. Case folder shows it in File "
            "Explorer. If a case with the same number is already saved, you can replace it or save a separate copy. "
            "A case opened from another location is copied into the case store when saved; the original is not changed. "
            "Removing a card or a photo deletes the case's copy of the photo at the next save."
        ),
    },
    {
        "title": "Card photos",
        "body": (
            "Each card can have photos of its front and back. Import a photo file, or capture one with the computer's "
            "camera. The camera window shows an outline the size and shape of a standard card: hold the card flat inside "
            "it and avoid glare. Rotate turns the picture a quarter turn, and Crop to the card outline keeps only the "
            "card and a small border. After capturing, check that the card is sharp and readable, then use the photo or "
            "retake it. Every photo is stored in the case's Photos folder with a SHA-256 hash, and a captured photo "
            "is recorded as a camera capture with the time it was taken."
        ),
    },
    {
        "title": "Offline BIN list",
        "body": (
            "An offline BIN list is a CSV file of BINs and issuing banks imported into this program. "
            "Lookups check it first, and those lookups never leave this computer. "
            "The report names the list, its import date, and its SHA-256 so the source can be identified later. "
            "Like the online directory, a list is not a verification by the issuing bank."
        ),
    },
    {
        "title": "Issuer packet",
        "body": (
            "The issuer packet groups the cards by issuing bank, with the accounts to request records for. "
            "Each bank starts on a new page. "
            "Cards without an identified bank are listed last with their BINs."
        ),
    },
]


# Terms for the appendix of the exported report. Written for someone reading the report,
# not for someone using the program.
REPORT_TERMS: list[dict[str, str]] = [
    {
        "title": "Magnetic stripe tracks",
        "body": (
            "A card's magnetic stripe can hold up to three tracks of data. Payment cards normally use track 1, "
            "which carries the account number, the cardholder name and the expiration, and track 2, which carries "
            "the account number and expiration without the name. Track 3 is seldom used. The raw tracks in this "
            "report are the characters the card reader returned. On a reader that types like a keyboard, track 1 "
            "begins with %, track 2 with ; and track 3 with +, and each ends with ?."
        ),
    },
    {
        "title": "Account number and BIN",
        "body": (
            "The account number (primary account number, or PAN) identifies the card account. Its first 6 or 8 "
            "digits are the bank identification number (BIN), which identifies the card network and, where a "
            "directory lists it, the issuing bank."
        ),
    },
    {
        "title": "Stripe and printed card",
        "body": (
            "The examiner compared the account number, name and expiration printed on the card with the same "
            "fields read from the stripe. Matches means the two agree. Differs means they do not. Not compared "
            "means the examiner did not record that field. Names are compared word by word, ignoring order, "
            "punctuation and titles such as MR. A difference is the examiner's observation of the card against "
            "its stripe; by itself it is not a determination that the card is counterfeit."
        ),
    },
    {
        "title": "Track comparison",
        "body": (
            "Where both track 1 and track 2 were read, the account number, expiration and service code on the two "
            "tracks are compared. On a card issued by a bank they normally agree. Data that differs between the "
            "tracks is reported as a finding."
        ),
    },
    {
        "title": "Luhn check",
        "body": (
            "A public checksum built into account numbers. A pass means the last digit is consistent with the "
            "others; a fail means it is not. A pass does not show that an account exists or was issued."
        ),
    },
    {
        "title": "Expiration and service code",
        "body": (
            "The expiration is stored on the stripe as year and month and is shown here as MM/YYYY. The service "
            "code is three digits that describe where the card may be used, how transactions are authorized, and "
            "whether a PIN is required. Its meaning is listed beneath it."
        ),
    },
    {
        "title": "Discretionary data",
        "body": (
            "Characters after the service code that the issuer defines for its own use. They are shown as read "
            "and are not interpreted."
        ),
    },
    {
        "title": "Stripe format",
        "body": (
            "Bank format means the stripe follows the layout used for credit and debit cards. Partial bank format "
            "means some of that layout is present. Non-standard or proprietary means the stripe uses another "
            "layout, as many gift, loyalty, hotel and access cards do."
        ),
    },
    {
        "title": "Card type",
        "body": (
            "What the examiner recorded the physical card to be: a bank card, gift card, hotel key or access card, "
            "ID or membership card, blank or white plastic, or other. A bank-format stripe on a card that is not "
            "printed as a bank card is reported as a finding."
        ),
    },
    {
        "title": "Flags",
        "body": (
            "Track read error: the reader could not read one of the tracks, so that track is not compared. "
            "Card type mismatch: the card type does not fit the stripe. Duplicate account: the same account "
            "number appears on another card in this case."
        ),
    },
    {
        "title": "Account length",
        "body": (
            "Each card network issues account numbers of particular lengths. A finding is added when the length "
            "does not fit the network suggested by the leading digits."
        ),
    },
    {
        "title": "Issuing bank",
        "body": (
            "The issuing bank is looked up from the BIN in a directory. Only the BIN is sent for the lookup. "
            "Directory listings can be incomplete or out of date and are not a confirmation from the bank."
        ),
    },
]
