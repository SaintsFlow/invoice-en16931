# Schemas kept in the repository

## ubl-2.1

The OASIS UBL 2.1 XML schemas, used by `tests/test_ubl.py` to check that the XML this
service produces is really UBL and not merely XML that looks like it. Without that
check the whole rendering step is a guess.

These are the runtime schemas, `xsdrt` in the OASIS distribution: the same rules as the
annotated `xsd` set, with the documentation stripped out. That takes the Invoice tree
from about six megabytes down to six hundred kilobytes.

Only what `UBL-Invoice-2.1.xsd` actually imports is here, worked out by following
`schemaLocation` until nothing new turned up. Fourteen files. The other seventy odd
document types in UBL, from bills of lading to tender receipts, are not.

Source: <https://docs.oasis-open.org/ubl/os-UBL-2.1/UBL-2.1.zip>, the OASIS Standard
of 4 November 2013. Do not edit these files. If they ever need updating, take the new
archive and repeat the import walk.
