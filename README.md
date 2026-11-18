# Card Stripe Examiner

Version 1.4.0. A read-only Windows program for reviewing magnetic-stripe cards. It keeps a case, reads all three tracks, checks the Luhn digit, compares the stripe with the printed card, and writes a PDF report, a spreadsheet, and an issuer packet.

The program does not write or encode a stripe.

## Install

Download `CardStripeExaminer-Setup-1.4.0.exe` from the [v1.4.0 release](https://github.com/koebbe14/Card-Stripe-Examiner/releases/tag/v1.4.0). The installer is attached to that release.

It installs on Windows 10 or 11. Python does not need to be installed. The install is for the current user and does not need administrator rights. An administrator can choose to install for all users. It adds a Start menu shortcut and an optional desktop shortcut, and it can be removed from Windows Settings > Apps. Installing a newer version over an older one upgrades it. Saved cases are not touched.

The installer is not code-signed, so Windows SmartScreen may show "Windows protected your PC" the first time it runs. Choose **More info**, then **Run anyway**. An agency code-signing certificate can be applied to the installer if one is available.

## How to use it

1. Start a case. You can set an exhibit prefix and a first number, for example `Item` and `1`.
2. Choose **Identify reader**, then swipe one card. After that, the case listens only to that reader. **Paste swipe** is available when the reader is not identified. Paste the raw characters, including sentinels such as `%`, `;`, `+`, and `?`.
3. Each swipe takes the next exhibit number. On the Summary tab, record what the plastic is: bank card, gift card, hotel key, ID, blank plastic, or other. A bank-format stripe on a non-bank card is reported as a finding.
4. If the reader cannot read a track, it types `E` (for example `%E?`). That track is shown as a **read error**, with a prompt to swipe again. A swipe in which every track failed is not added to the case.
5. Add front and back photos, look up the issuing bank, and save the case.
6. Export a PDF report, a spreadsheet, or an issuer packet.

## Readers

The program listens to a USB reader that Windows presents as a keyboard. It does not install a reader driver, and it does not contain a list of approved model numbers. After **Identify reader**, later swipes are taken only from the device you swiped.

A usable reader types standard track characters. Track 1 starts with `%` and uses `^`. Track 2 starts with `;` and uses `=` (some readers type `D` in that position). Track 3 starts with `+`. Each track ends with `?`. The reader can end the swipe with Enter, or it can simply pause. An unreadable track is typed as `E`.

To check a reader before using it here, swipe a card in Notepad. A usable swipe looks like `%B...^...^...?;...=...`.

- **Adesso MSR-100.** This is the reader the program was built for. It is a three-track USB keyboard-wedge reader on a MagTek chipset. The program treats USB vendor `0801` and product `0001` as the same reader if you unplug it and plug it back in. That is MagTek's keyboard-emulation ID.
- **Other MagTek readers in keyboard-emulation mode.** The same USB ID (`0801` / `0001`) is used by MagTek's USB keyboard-emulation swipe reader, SureSwipe, IntelliHead, the full-size keyboard-emulation swipe reader, and swipe or insert readers that are set to keyboard emulation. Choose **Identify reader** and swipe once. Set the reader to US keyboard emulation, which is the usual default.
- **Other USB keyboard-wedge readers.** Any other reader that types those same sentinels into Notepad can be selected with **Identify reader**. That binds the reader by its own device path. These readers are compatible because of the characters they type. Individual models other than the MSR-100 have not been certified here. A custom keymap, or an international mode that types characters with Alt and the numeric keypad, is not decoded.

**Paste swipe** accepts that same character string from the clipboard, including a swipe you copied out of Notepad.

The program does not read serial or RS-232 readers, USB readers that use a vendor protocol instead of typing, or encrypted and tokenized output that is not clear track text. MagTek HID mode uses a different product ID (`0002`, and MagneSafe IDs such as `0011`) and is not a keyboard, so that mode is not read. Chip-only and contactless-only readers are not read.

## Case

- **Exhibit numbers.** A new case can have an exhibit prefix and a first number (for example `Item ` and `1`). Each swipe takes the next number. Edit it on the Summary tab to match the evidence label. When a card is removed, the cards swiped after it are renumbered so the exhibit numbers stay in order with no gaps. A label you typed in another form (for example `Item 7A`) is left as it is. Photo file names keep the exhibit label they were saved with.
- **Card type.** Record what the plastic is: bank card, gift card, hotel key, ID, blank plastic, or other. A bank-format stripe on a non-bank card is reported as a finding.
- **Duplicates.** Cards that share an account number, on any track, are listed against each other. Identical swipes are reported separately.
- **Photos.** Add front and back photos on the Summary tab, either by importing a photo file or by capturing one with the computer's camera (**Capture front/back photo**). The camera window shows a card-shaped outline to line the card up in, can rotate the picture and crop to the outline, and lets you retake before keeping the photo. Photos are kept in the case's `Photos` folder, with a SHA-256 for each, and camera captures are marked as such. Removing a card, or a single photo, deletes the case's copy of the photo when you save. An imported photo's original file is not affected. If no camera picture appears, check Windows Settings > Privacy & security > Camera, including "Let desktop apps access your camera".
- **Autosave.** The open case is saved to a recovery copy every 30 seconds and after every swipe. If the program closes unexpectedly, it offers to recover the case the next time it starts. Recovery copies are kept in `%LOCALAPPDATA%\CardStripeExaminer\autosave` and removed when the case is saved.

## Issuing bank

**Look up bank** checks, in order:

1. An **offline BIN list**, if one is imported (**Offline BIN list** on the Summary tab). The list is a CSV whose first row names the columns, for example `bin, issuer, brand, type, country`. These lookups never leave the computer.
2. Earlier online answers saved on this computer. A found bank is reused for 6 months, and a "not listed" answer for 7 days.
3. **lookup.binlist.net**, only after you confirm the digits. Only the first 6 or 8 digits are sent. The rest of the account, the name, the expiration, and the case stay on this computer.

The report states which source each answer came from. The optional binlist.net service token is stored encrypted for your Windows account (DPAPI).

## Exports

- **Export PDF** writes the case report. It can include photos, raw tracks, and the glossary, and can mask account numbers.
- **Spreadsheet** writes one row per card as an Excel workbook (every value stored as text, so long account numbers keep all their digits) or a CSV.
- **Issuer packet** is a PDF grouped by issuing bank, with the accounts to request records for.

Unless you choose to mask them, exports contain full account numbers.

## Where cases are saved

**Save** puts each case in its own folder, named by case number, in `%LOCALAPPDATA%\CardStripeExaminer\Cases` (for example `C:\Users\<you>\AppData\Local\CardStripeExaminer\Cases\26-1847\`). The folder holds the case file (`26-1847.json`) and a `Photos` folder. **Case folder** opens it in File Explorer, and **Open** starts there. If a case with the same number is already saved, the program asks whether to replace it or save a separate copy (`26-1847 (2)`). A case opened from anywhere else is copied into the case store when you save it. The file you opened is not changed.

