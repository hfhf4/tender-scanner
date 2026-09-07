"""Source registry and status metadata."""
from tender_scanner.sources import alps, gebiz, nkf, renci

PUBLIC_SOURCES = [
    {"key":"gebiz","name":"GeBIZ","scanner":lambda seen: gebiz.scan("opportunities",seen),"url":gebiz.FEEDS["opportunities"],"authoritative":False},
    {"key":"renci","name":"Ren Ci Hospital","scanner":renci.scan,"url":renci.LISTING_URL,"authoritative":True},
    {"key":"alps","name":"ALPS Healthcare","scanner":alps.scan,"url":alps.LISTING_URL,"authoritative":True},
    {"key":"nkf","name":"National Kidney Foundation","scanner":nkf.scan,"url":nkf.PAGES["RFP"],"authoritative":True},
]

PORTALS = [
    {"key":"aic","name":"Agency for Integrated Care","status":"portal","url":"https://www.aic.sg/procurement","platform":"SAP Business Network"},
    {"key":"sap","name":"SAP Business Network / Ariba","status":"login_required","url":"https://supplier.ariba.com/","platform":"SAP Business Network"},
    {"key":"tenderboard","name":"TenderBoard Singapore","status":"planned","url":"https://www.tenderboard.biz/singaporetenders","platform":"TenderBoard"},
]
