# Card Stripe Examiner

Version 1.4.0

Card Stripe Examiner is a read-only Windows program for law-enforcement officers, digital-forensic analysts, and authorized investigative personnel who need to review magnetic-stripe cards during a criminal investigation. It is intended for the examination of cards suspected of being cloned or fraudulent, including bank cards, gift cards, hotel keys, identification cards, and blank plastic recovered in fraud, skimming, identity-theft, and related investigations.

The program reads the stripe, keeps the cards in a case, and produces records an investigator can use in the case file. It does not write or encode a stripe, and it does not alter an imported photograph's original file. A report documents what the stripe contained and what the examiner observed. It does not, by itself, determine that a card is cloned, counterfeit, or fraudulent.

Use is limited to authorized investigative personnel. The terms are in [LICENSE](LICENSE) and are repeated under [License](#license) below.

## Investigative use

An examiner can use the program to:

- Read all three tracks from a swiped card and preserve the raw characters the reader returned.
- Check the Luhn digit on an account number, as a consistency check on the digits that were read.
- Compare the account number, name, and expiration on the stripe with the same fields on the printed card, and record where they agree or differ.
- Record what the plastic is. A bank-format stripe on a gift card, hotel key, identification card, blank plastic, or other non-bank card is reported as a finding.
- Keep a case session with exhibit numbers that follow the evidence labels.
- Flag cards in the same case that share an account number, and report identical swipes separately.
- Photograph the front and back of each card, or import existing photographs, and keep a SHA-256 for each image stored with the case.
- Look up the issuing institution from the leading digits of the account number, from an offline list or from a confirmed online query.
- Export a case report, a spreadsheet of one row per card, and an issuer packet grouped for record requests.

## Install

Download `CardStripeExaminer-Setup-1.4.0.exe` from the [v1.4.0 release](https://github.com/koebbe14/Card-Stripe-Examiner/releases/tag/v1.4.0). The installer is attached to that release.

The program installs on Windows 10 or 11. Python is not required. Installation is for the current user and does not require administrator rights. An administrator may choose to install for all users. The installer adds a Start menu shortcut and an optional desktop shortcut. The program can be removed from Windows Settings > Apps. Installing a newer version over an older one upgrades the program. Saved cases are left in place.

The installer is not code-signed. Windows SmartScreen may show "Windows protected your PC" the first time it runs. Choose **More info**, then **Run anyway**. An agency code-signing certificate may be applied to the installer when one is available.

## Examination workflow

1. Open a case. Set an exhibit prefix and a starting number when the evidence is already labeled, for example `Item` and `1`.
2. Choose **Identify reader**, then swipe one card. Later swipes in that case are taken only from that reader. When the reader has not been identified, **Paste swipe** accepts the raw characters, including the sentinels `%`, `;`, `+`, and `?`.
3. Each swipe receives the next exhibit number. On the Summary tab, record the card type: bank card, gift card, hotel key, ID, blank plastic, or other.
4. A track the reader cannot read is typed as `E` (for example `%E?`) and shown as a read error, with a prompt to swipe the card again. A swipe in which every track failed is not added to the case.
5. Add front and back photographs, look up the issuing bank, and compare the stripe with the printed card.
6. Save the case, then export the PDF report, the spreadsheet, or the issuer packet.

## What a case records

- **Exhibit numbers.** A new case can carry an exhibit prefix and a first number (for example `Item ` and `1`). Each swipe takes the next number. Edit the number on the Summary tab so it matches the evidence label. When a card is removed, later cards that still use automatic numbers are renumbered so the sequence has no gaps. A label typed in another form, such as `Item 7A`, is left unchanged. Photograph file names keep the exhibit label they were saved with.
- **Card type.** Record what the plastic is. A bank-format stripe on a non-bank card is reported as a finding.
- **Duplicates.** Cards that share an account number on any track are listed against each other. Identical swipes are reported as their own entries.
- **Photographs.** Add front and back photographs on the Summary tab by importing a file or by capturing one with the computer's camera (**Capture front/back photo**). The camera window shows a card-shaped outline, and it can rotate the picture, crop to the outline, and retake the photograph before it is kept. Photographs are stored in the case's `Photos` folder. Each stored image has a SHA-256, and a camera capture is marked as such. Removing a card, or a single photograph, deletes the case's copy when the case is saved. The original file of an imported photograph is not changed. If the camera shows no picture, check Windows Settings > Privacy & security > Camera, including "Let desktop apps access your camera".
- **Autosave.** The open case is written to a recovery copy every 30 seconds and after every swipe. If the program closes unexpectedly, the next start offers to recover that case. Recovery copies are kept in `%LOCALAPPDATA%\CardStripeExaminer\autosave` and are removed when the case is saved.

## Readers

The program reads a USB magnetic-stripe reader that Windows presents as a keyboard. It does not install a reader driver, and it does not certify a list of models. After **Identify reader**, the case listens only to the device that was swiped.

A reader suitable for this examination types standard track characters. Track 1 starts with `%` and uses `^`. Track 2 starts with `;` and uses `=` (some readers type `D` in that position). Track 3 starts with `+`. Each track ends with `?`. The reader may end the swipe with Enter, or it may pause. An unreadable track is typed as `E`.

Before relying on a reader, swipe a card in Notepad. A usable swipe looks like `%B...^...^...?;...=...`.

- **Adesso MSR-100.** This is the reader the program was built for. It is a three-track USB keyboard-wedge reader on a MagTek chipset. USB vendor `0801` and product `0001` are treated as the same reader if the device is unplugged and plugged back in. That is MagTek's keyboard-emulation identifier.
- **Other MagTek readers in keyboard-emulation mode.** The same USB identifier (`0801` / `0001`) is used by MagTek's USB keyboard-emulation swipe reader, SureSwipe, IntelliHead, the full-size keyboard-emulation swipe reader, and swipe or insert readers set to keyboard emulation. Choose **Identify reader** and swipe once. The reader should be set to US keyboard emulation, which is the usual default.
- **Other USB keyboard-wedge readers.** Any other reader that types those sentinels into Notepad can be selected with **Identify reader**. The program then binds that device by its own path. Compatibility follows from the characters the reader types. Models other than the MSR-100 have not been individually qualified. A custom keymap, or an international mode that sends characters with Alt and the numeric keypad, is not decoded.

**Paste swipe** accepts the same character string from the clipboard, including a swipe copied from Notepad.

Serial and RS-232 readers are not read. USB readers that use a vendor protocol, and encrypted or tokenized output that is not clear track text, are not read. MagTek HID mode uses a different product identifier (`0002`, and MagneSafe identifiers such as `0011`) and is not a keyboard, so that mode is not read. Chip-only and contactless-only readers are not read.

## Issuing institution

**Look up bank** checks the leading digits of the account number in this order:

1. An offline BIN list, when one has been imported (**Offline BIN list** on the Summary tab). The list is a CSV whose first row names the columns, for example `bin, issuer, brand, type, country`. These lookups never leave the computer.
2. Earlier online answers saved on this computer. A found institution is reused for 6 months. A "not listed" answer is reused for 7 days.
3. lookup.binlist.net, only after the examiner confirms the digits. Only the first 6 or 8 digits are sent. The rest of the account, the name, the expiration, and the case remain on the computer.

The report states which source supplied each answer. An optional binlist.net service token is stored encrypted for the Windows account (DPAPI). A directory answer identifies a published issuer range. It is not confirmation from the issuing bank.

## Reports and exports

- **Export PDF** writes the case report. The report can include photographs, raw tracks, and a glossary, and it can mask account numbers.
- **Spreadsheet** writes one row per card as an Excel workbook or a CSV file. Every value is stored as text, so a long account number keeps all of its digits.
- **Issuer packet** is a PDF grouped by issuing institution, with the accounts for which records may be requested.

Unless masking is selected, exports contain full account numbers. Treat the case folder and every export as sensitive investigative material.

## Where cases are saved

**Save** places each case in its own folder, named by case number, under `%LOCALAPPDATA%\CardStripeExaminer\Cases` (for example `C:\Users\<you>\AppData\Local\CardStripeExaminer\Cases\26-1847\`). The folder holds the case file (`26-1847.json`) and a `Photos` folder. **Case folder** opens that location in File Explorer, and **Open** starts there. If a case with the same number is already saved, the program asks whether to replace it or save a separate copy (`26-1847 (2)`). A case opened from another location is copied into the case store when it is saved. The file that was opened is not changed.

## License

Permission is hereby granted to law-enforcement agencies, digital-forensic analysts, and authorized investigative personnel ("Authorized Users") to use and copy Card Stripe Examiner for the purpose of criminal investigations, evidence review, training, or internal operational use. That use includes the review of magnetic-stripe cards suspected of being cloned or fraudulent.

The following conditions apply:

**Redistribution.** Card Stripe Examiner may not be sold, published, or redistributed to the general public. Redistribution outside an authorized agency requires written permission from the developer.

**No warranty.** Card Stripe Examiner is provided "AS IS," without warranty of any kind, express or implied, including but not limited to the warranties of accuracy, completeness, performance, non-infringement, or fitness for a particular purpose. The developer shall not be liable for any claim, damages, or other liability arising from the use of this software, including the review of magnetic-stripe evidence, issuer lookups, comparisons, or reports produced by the program.

**Evidence integrity.** Users are responsible for maintaining forensic integrity and chain of custody when handling evidence. Card Stripe Examiner does not write or encode a magnetic stripe, and it does not modify an imported photograph's original file. The program is intended only for analysis and review. A report records what was read and what the examiner entered. It does not, by itself, determine that a card is cloned, counterfeit, or fraudulent. Users remain responsible for exhibit labeling, the accuracy of any comparison with the printed card, and any conclusion drawn from the results.

**Modifications.** Agencies and investigators may modify the software for internal purposes. Modified versions may not be publicly distributed without permission from the developer.

**Logging and privacy.** Case files, photographs, reports, spreadsheets, and issuer packets may contain full account numbers, cardholder names, and other sensitive or personally identifiable information. Users are responsible for controlling those files, and any other output generated during use, to prevent unauthorized disclosure. An optional online issuer lookup transmits only the first 6 or 8 digits of an account number, and only after the user confirms that transmission. The remainder of the account, the name, the expiration, and the case stay on the computer.

**Compliance.** Users agree to comply with all applicable laws, departmental policies, and legal requirements when using the software.

By using this software, the user acknowledges that they have read, understood, and agreed to the above terms.

These terms are also recorded in [LICENSE](LICENSE).
