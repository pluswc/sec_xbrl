"""SEC-specific Inline XBRL transformations missing from arelle-release.

The SEC EFM defines these transformations in the 2015-08-31 namespace.  They
are executable parser dependencies, not filing-taxonomy resources, so they are
registered before both online bootstrap and offline Arelle loads.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal, localcontext
from typing import Any

from regex import compile as regex_compile

SEC_TRANSFORM_NAMESPACE = "http://www.sec.gov/inlineXBRL/transformation/2015-08-31"

_NUMBER_WORDS = {
    "zero": 0, "no": 0, "none": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
# SEC-staff public-domain name/code tables, copied verbatim (17 U.S.C. 105).
# https://github.com/Arelle/EDGAR/blob/master/transform/__init__.py
# Retrieved 2026-10-13; source SHA-256:
# 2296586f945ffd95ab37d3d4147c4e45f42ce4e5f397f61143e053208adefbf1
_COUNTRY_NAME_RE = regex_compile(r"^[ \t\n\r]*(([Aa]fghanistan)|([ÅåAa]land\s+[Ii]slands)|([Aa]lbania)|([Aa]lgeria)|([Aa]merican\s+[Ss]amoa)|([Aa]ndorra)|([Aa]ngola)|([Aa]nguilla)|([Aa]ntarctica)|([Aa]ntigua\s+[Aa]nd\s+[Bb]arbuda)|((([Tt]he\s+)?[Rr]epublic\s+[Oo]f\s+)?[Aa]rgentina)|([Aa]rmenia)|([Aa]ruba)|([Aa]ustralia)|([Aa]ustria)|([Aa]zerbaijan)|([Bb]ahamas)|([Bb]ahrain)|([Bb]angladesh)|([Bb]arbados)|([Bb]elarus)|([Bb]elgium)|([Bb]elize)|([Bb]enin)|([Bb]ermuda)|([Bb]hutan)|([Bb]olivia)|([Bb]onaire,\s+[Ss]int\s+[Ee]ustatius\s+[Aa]nd\s+[Ss]aba)|([Bb]osnia\s+[Aa]nd\s+[Hh]erzegovina)|([Bb]otswana)|([Bb]ouvet\s+[Ii]sland)|((([Tt]he\s+)?[Ff]ederative\s+[Rr]epublic\s+[Oo]f\s+)?[Bb]ra[sz]il)|([Bb]ritish\s+[Ii]ndian\s+[Oo]cean\s+[Tt]erritory)|([Bb]runei\s+[Dd]arussalam)|([Bb]ulgaria)|([Bb]urkina\s+[Ff]aso)|([Bb]urundi)|([Cc]abo\s+[Vv]erde)|([Cc]ambodia)|([Cc]ameroon)|([Cc]anada)|([Cc]ayman\s+[Ii]slands)|([Cc]entral\s+[Aa]frican\s+[Rr]epublic)|([Cc]had)|([Cc]hile)|((([Tt]he\s+)?[Pp]eople['’]?s\s+[Rr]epublic\s+[Oo]f\s+)?[Cc]hina)|([Cc]hristmas\s+[Ii]sland)|([Cc]ocos\s+(.[Kk]eeling.\s+)?[Ii]slands)|((([Tt]he\s+)?[Rr]epublic\s+[Oo]f\s+)?[Cc]olombia)|([Cc]omoros)|([Dd]emocratic\s+[Rr]epublic\s+[Oo]f\s+([Tt]he\s+)?[Cc]ongo)|([Cc]ongo)|([Cc]ook\s+[Ii]slands)|([Cc]osta\s+[Rr]ica)|([Cc][ôo]te\s+d['’][Ii]voire)|([Cc]roatia)|([Cc]uba)|([Cc]ura[çc]ao)|([Cc]yprus)|([Cc]zechia|[Cc]zech\s+[Rr]epublic)|((([Tt]he\s+)?[Kk]ingdom\s+[Oo]f\s+)?[Dd]enmark)|([Dd]jibouti)|([Dd]ominica)|([Dd]ominican\s+[Rr]epublic)|([Ee]cuador)|([Ee]gypt)|([Ee]l\s+[Ss]alvador)|([Ee]quatorial\s+[Gg]uinea)|([Ee]ritrea)|([Ee]stonia)|([Ee]swatini)|([Ee]thiopia)|(([Tt]he\s+)?[Ff]alkland\s+[Ii]slands(\s+.[Mm]alvinas.)?|([Ii]slas\s+)?[Mm]alvinas(\s+[Ii]slands)?)|([Ff]aroe\s+[Ii]slands)|([Ff]iji)|([Ff]inland)|([Ff]rance)|([Ff]rench\s+[Gg]uiana)|([Ff]rench\s+[Pp]olynesia)|([Ff]rench\s+[Ss]outhern\s+[Tt]erritories)|([Gg]abon)|([Gg]ambia)|([Gg]eorgia)|([Gg]ermany)|([Gg]hana)|([Gg]ibraltar)|([Gg]reece)|([Gg]reenland)|([Gg]renada)|([Gg]uadeloupe)|([Gg]uam)|([Gg]uatemala)|([Gg]uernsey)|([Gg]uinea)|([Gg]uinea-[Bb]issau)|([Gg]uyana)|([Hh]aiti)|([Hh]eard\s+[Ii]sland\s+[Aa]nd\s+[Mm]cDonald\s+[Ii]slands)|(([Tt]he\s+)?[Hh]oly\s+[Ss]ee|[Vv]atican\s+[Cc]ity)|([Hh]onduras)|([Hh]ong\s+[Kk]ong)|([Hh]ungary)|([Ii]celand)|([Ii]ndia)|([Ii]ndonesia)|((([Tt]he\s+)?[Ii]slamic\s+[Rr]epublic\s+of\s+)?[Ii]ran)|([Ii]raq)|([Ii]reland)|([Ii]sle\s+[Oo]f\s+[Mm]an)|([Ii]srael)|([Ii]taly)|([Jj]amaica)|([Jj]apan)|([Jj]ersey)|([Jj]ordan)|([Kk]azakhstan)|([Kk]enya)|([Kk]iribati)|(([Nn]orth|[Dd]emocratic\s+[Pp]eople['’]?s\s+[Rr]epublic\s+[Oo]f)\s+[Kk]orea)|(([Ss]outh|[Rr]epublic\s+[Oo]f)\s+[Kk]orea)|([Kk]uwait)|([Kk]yrgyzstan)|([Ll]ao\s+[Pp]eople['’]?s\s+[Dd]emocratic\s+[Rr]epublic)|([Ll]atvia)|([Ll]ebanon)|([Ll]esotho)|([Ll]iberia)|((([Tt]he\s+)?[Ss]tate\s+[Oo]f\s+)?[Ll]ibya)|([Ll]iechtenstein)|([Ll]ithuania)|((([Tt]he\s+)?([Gg]rand\s+)?[Dd]uchy\s+[Oo]f\s+)?[Ll]uxembourg)|([Mm]aca[ou])|([Mm]adagascar)|([Mm]alawi)|([Mm]alaysia)|([Mm]aldives)|([Mm]ali)|([Mm]alta)|((([Tt]he\s+)?[Rr]epublic\s+[Oo]f\s+([Tt]he\s+)?)?[Mm]arshall\s+[Ii]slands)|([Mm]artinique)|([Mm]auritania)|([Mm]auritius)|([Mm]ayotte)|([Mm]exico|[Uu]nited\s+[Mm]exican\s+[Ss]tates)|((([Tt]he\s+)?[Ff]ederated\s+[Ss]tates\s+[Oo]f\s+)?[Mm]icronesia)|((([Tt]he\s+)?[Rr]epublic\s+[Oo]f\s+)?[Mm]oldova)|([Mm]onaco)|([Mm]ongolia)|([Mm]ontenegro)|([Mm]ontserrat)|([Mm]orocco)|([Mm]ozambique)|([Mm]yanmar)|([Nn]amibia)|([Nn]auru)|([Nn]epal)|([Nn]etherlands)|([Nn]ew\s+[Cc]aledonia)|([Nn]ew\s+[Zz]ealand)|([Nn]icaragua)|([Nn]iger)|([Nn]igeria)|([Nn]iue)|([Nn]orfolk\s+[Ii]sland)|((([Tt]he\s+)?[Rr]epublic\s+[Oo]f\s+)?[Nn]orth\s+[Mm]acedonia)|([Nn]orthern\s+[Mm]ariana\s+[Ii]slands)|([Nn]orway)|([Oo]man)|([Pp]akistan)|([Pp]alau)|((([Tt]he\s+)?[Ss]tate\s+[Oo]f\s+)?[Pp]alestine)|([Pp]anama)|([Pp]apua\s+[Nn]ew\s+[Gg]uinea)|([Pp]araguay)|([Pp]eru)|([Pp]hilippines)|([Pp]itcairn)|([Pp]oland)|([Pp]ortugal)|([Pp]uerto\s+[Rr]ico)|([Qq]atar)|([Rr][ée]union)|([Rr]omania)|([Rr]ussian\s+[Ff]ederation)|([Rr]wanda)|([Ss]aint\s+[Bb]arth[ée]lemy)|([Ss]aint\s+[Hh]elena(,\s+[Aa]scension,?\s+[Aa]nd\s+[Tt]ristan(\s+[Dd]a\s+[Cc]unha)?)?)|([Ss]aint\s+[Kk]itts\s+[Aa]nd\s+[Nn]evis)|([Ss]aint\s+[Ll]ucia)|([Ss]aint\s+[Mm]artin)|([Ss]aint\s+[Pp]ierre\s+[Aa]nd\s+[Mm]iquelon)|([Ss]aint\s+[Vv]incent(\s+[Aa]nd\s+([Tt]he\s+)?[Gg]renadines)?)|([Ss]amoa)|([Ss]an\s+[Mm]arino)|([Ss]ao\s+[Tt]ome\s+[Aa]nd\s+[Pp]rincipe)|([Ss]audi\s+[Aa]rabia)|([Ss]enegal)|([Ss]erbia)|([Ss]eychelles)|([Ss]ierra\s+[Ll]eone)|([Ss]ingapore)|([Ss]int\s+[Mm]aarten)|([Ss]lovakia)|([Ss]lovenia)|([Ss]olomon\s+[Ii]slands)|([Ss]omalia)|((([Tt]he\s+)?[Rr]epublic\s+[Oo]f\s+)?[Ss]outh\s+[Aa]frica)|([Ss]outh\s+[Gg]eorgia\s+[Aa]nd\s+([Tt]he\s+)?[Ss]outh\s+[Ss]andwich\s+[Ii]slands)|([Ss]outh\s+[Ss]udan)|((([Tt]he\s+)?[Kk]ingdom\s+[Oo]f\s+)?[Ss]pain|[Ee]spa[ñn]a)|([Ss]ri\s+[Ll]anka)|([Ss]udan)|([Ss]uriname)|([Ss]valbard\s+[Aa]nd\s+[Jj]an\s+[Mm]ayen)|([Ss]weden)|([Ss]witzerland)|([Ss]yria(n\s+[Aa]rab\s+[Rr]epublic)?)|([Tt]aiwan(,?\s+[Pp]rovince\s+[Oo]f\s+[Cc]hina)?)|([Tt]ajikistan)|((([Tt]he\s+)?[Uu]nited\s+[Rr]epublic\s+[Oo]f\s+)?[Tt]anzania)|([Tt]hailand)|([Tt]imor-[Ll]este)|([Tt]ogo)|([Tt]okelau)|([Tt]onga)|([Tt]rinidad\s+[Aa]nd\s+[Tt]obago)|([Tt]unisia)|([Tt][uü]rk(ey|iye))|([Tt]urkmenistan)|([Tt]urks\s+[Aa]nd\s+[Cc]aicos\s+[Ii]slands)|([Tt]uvalu)|([Uu]ganda)|([Uu]kraine)|(UAE|[Uu]nited\s+[Aa]rab\s+[Ee]mirates)|(U[.]?K[.]?|[Bb]ritain|[Gg]reat\s+[BBb]ritain|[Uu]nited\s+[Kk]ingdom(\s+[Oo]f\s+[Gg]reat\s+[Bb]ritain\s+[Aa]nd\s+[Nn]orthern\s+[Ii]reland)?|[Ee]ngland(\s+[Aa]nd\s+[Ww]ales)?)|([Uu]nited\s+[Ss]tates\s+[Mm]inor\s+[Oo]utlying\s+[Ii]slands)|(U[.]?S[.]?A[.]?|[Uu]nited\s+[Ss]tates(\s+[Oo]f\s+[Aa]merica)?)|([Uu]ruguay)|([Uu]zbekistan)|([Vv]anuatu)|([Vv]enezuela)|([Vv]iet\s+[Nn]am)|([Bb]ritish\s+[Vv]irgin\s+[Ii]slands)|([Uu][.]?[Ss][.]?\s+[Vv]irgin\s+[Ii]slands)|([Ww]allis\s+[Aa]nd\s+[Ff]utuna)|([Ww]estern\s+[Ss]ahara*)|([Yy]emen)|([Zz]ambia)|([Zz]imbabwe))[ \t\n\r]*$")
_COUNTRY_CODES = ("AF", "AX", "AL", "DZ", "AS", "AD", "AO", "AI", "AQ", "AG", "AR", "AM", "AW", "AU", "AT", "AZ", "BS", "BH", "BD", "BB", "BY", "BE", "BZ", "BJ", "BM", "BT", "BO", "BQ", "BA", "BW", "BV", "BR", "IO", "BN", "BG", "BF", "BI", "CV", "KH", "CM", "CA", "KY", "CF", "TD", "CL", "CN", "CX", "CC", "CO", "KM", "CD", "CG", "CK", "CR", "CI", "HR", "CU", "CW", "CY", "CZ", "DK", "DJ", "DM", "DO", "EC", "EG", "SV", "GQ", "ER", "EE", "SZ", "ET", "FK", "FO", "FJ", "FI", "FR", "GF", "PF", "TF", "GA", "GM", "GE", "DE", "GH", "GI", "GR", "GL", "GD", "GP", "GU", "GT", "GG", "GN", "GW", "GY", "HT", "HM", "VA", "HN", "HK", "HU", "IS", "IN", "ID", "IR", "IQ", "IE", "IM", "IL", "IT", "JM", "JP", "JE", "JO", "KZ", "KE", "KI", "KP", "KR", "KW", "KG", "LA", "LV", "LB", "LS", "LR", "LY", "LI", "LT", "LU", "MO", "MG", "MW", "MY", "MV", "ML", "MT", "MH", "MQ", "MR", "MU", "YT", "MX", "FM", "MD", "MC", "MN", "ME", "MS", "MA", "MZ", "MM", "NA", "NR", "NP", "NL", "NC", "NZ", "NI", "NE", "NG", "NU", "NF", "MK", "MP", "NO", "OM", "PK", "PW", "PS", "PA", "PG", "PY", "PE", "PH", "PN", "PL", "PT", "PR", "QA", "RE", "RO", "RU", "RW", "BL", "SH", "KN", "LC", "MF", "PM", "VC", "WS", "SM", "ST", "SA", "SN", "RS", "SC", "SL", "SG", "SX", "SK", "SI", "SB", "SO", "ZA", "GS", "SS", "ES", "LK", "SD", "SR", "SJ", "SE", "CH", "SY", "TW", "TJ", "TZ", "TH", "TL", "TG", "TK", "TO", "TT", "TN", "TR", "TM", "TC", "TV", "UG", "UA", "AE", "GB", "UM", "US", "UY", "UZ", "VU", "VE", "VN", "VG", "VI", "WF", "EH", "YE", "ZM", "ZW")
_STATE_PROVINCE_NAME_RE = regex_compile(r"^[ \t\n\r]*(([Aa]labama)|([Aa]laska)|([Aa]rizona)|([Aa]rkansas)|([Cc]alifornia)|([Cc]olorado)|([Cc]onnecticut)|([Dd]elaware)|([Ff]lorida)|([Gg]eorgia)|([Hh]awaii)|([Ii]daho)|([Ii]llinois)|([Ii]ndiana)|([Ii]owa)|([Kk]ansas)|([Kk]entucky)|([Ll]ouisiana)|([Mm]aine)|([Mm]aryland)|([Mm]assachusetts)|([Mm]ichigan)|([Mm]innesota)|([Mm]ississippi)|([Mm]issouri)|([Mm]ontana)|([Nn]ebraska)|([Nn]evada)|([Nn]ew\s+[Hh]ampshire)|([Nn]ew\s+[Jj]ersey)|([Nn]ew\s+[Mm]exico)|([Nn]ew\s+[Yy]ork)|([Nn]orth\s+[Cc]arolina)|([Nn]orth\s+[Dd]akota)|([Oo]hio)|([Oo]klahoma)|([Oo]regon)|([Pp]ennsylvania)|([Rr]hode\s+[Ii]sland)|([Ss]outh\s+[Cc]arolina)|([Ss]outh\s+[Dd]akota)|([Tt]ennessee)|([Tt]exas)|([Uu]tah)|([Vv]ermont)|([Vv]irginia)|([Ww]ashington)|([Ww]est\s+[Vv]irginia)|([Ww]isconsin)|([Ww]yoming)|([Dd]istrict\s+[Oo]f\s+[Cc]olumbia)|(([Aa]merican\s+)?[Ss]amoa)|([Gg]uam)|([Nn]orthern\s+[Mm]ariana\s+[Ii]slands)|([Pp]uerto\s+[Rr]ico)|([Uu]nited\s+[Ss]tates\s+[Mm]inor\s+[Oo]utlying\s+[Ii]slands)|([Vv]irgin\s+[Ii]slands,\s+U[.]S[.])|([Aa]lberta)|([Bb]ritish\s+[Cc]olumbia)|([Mm]anitoba)|([Nn]ew\s+[Bb]runswick)|([Nn]ewfoundland(\s+[Aa]nd\s+[Ll]abrador)?)|([Nn]ova\s+[Ss]cotia)|([Nn]orthwest\s+[Tt]erritories)|([Nn]unavut)|([Oo]ntario)|([Pp]rince\s+[Ee]dward\s+[Ii]sland)|([Qq]u[eé]bec)|([Ss]askatchewan)|([Yy]ukon))[ \t\n\r]*$")
_STATE_PROVINCE_CODES = ("AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC", "AS", "GU", "MP", "PR", "UM", "VI", "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT")
_EDGAR_PROVINCE_COUNTRY_NAME_RE = regex_compile(r"^[ \t\n\r]*(([Aa]merican\s+[Ss]amoa)|([Gg]uam)|([Pp]uerto\s+[Rr]ico)|([Uu]nited\s+[Ss]tates\s+[Mm]inor\s+[Oo]utlying\s+[Ii]slands)|([Vv]irgin\s+[Ii]slands,\s+U[.]?S[.]?|U([.]\s*)?S[.]?\s+[Vv]irgin\s+[Ii]slands)|([Aa]lberta(,?\s+[Cc]anada)?)|([Bb]ritish\s+[Cc]olumbia(,?\s+[Cc]anada)?)|([Mm]anitoba(,?\s+[Cc]anada)?)|([Nn]ew\s+[Bb]runswick(,?\s+[Cc]anada)?)|([Nn]ewfoundland(\s+[Aa]nd\s+[Ll]abrador)?(,?\s+[Cc]anada)?)|([Nn]ova\s+[Ss]cotia(,?\s+[Cc]anada)?)|([Oo]ntario(,?\s+[Cc]anada)?)|([Pp]rince\s+[Ee]dward\s+[Ii]sland(,?\s+[Cc]anada)?)|([Qq]u[eé]bec(,?\s+[Cc]anada)?)|([Ss]askatchewan(,?\s+[Cc]anada)?)|([Yy]ukon(,?\s+[Cc]anada)?)|([Aa]fghanistan)|([ÅåAa]land\s+[Ii]slands)|([Aa]lbania)|([Aa]lgeria)|([Aa]merican\s+[Ss]amoa)|([Aa]ndorra)|([Aa]ngola)|([Aa]nguilla)|([Aa]ntarctica)|([Aa]ntigua\s+[Aa]nd\s+[Bb]arbuda)|((([Tt]he\s+)?[Rr]epublic\s+[Oo]f\s+)?[Aa]rgentina)|([Aa]rmenia)|([Aa]ruba)|([Aa]ustralia)|([Aa]ustria)|([Aa]zerbaijan)|([Bb]ahamas)|([Bb]ahrain)|([Bb]angladesh)|([Bb]arbados)|([Bb]elarus)|([Bb]elgium)|([Bb]elize)|([Bb]enin)|([Bb]ermuda)|([Bb]hutan)|([Bb]olivia)|([Bb]osnia\s+[Aa]nd\s+[Hh]erzegovina)|([Bb]otswana)|([Bb]ouvet\s+[Ii]sland)|((([Tt]he\s+)?[Ff]ederative\s+[Rr]epublic\s+[Oo]f\s+)?[Bb]ra[sz]il)|([Bb]ritish\s+[Ii]ndian\s+[Oo]cean\s+[Tt]erritory)|([Bb]runei\s+[Dd]arussalam)|([Bb]ulgaria)|([Bb]urkina\s+[Ff]aso)|([Bb]urundi)|([Cc]a(bo|pe)\s+[Vv]erde)|([Cc]ambodia)|([Cc]ameroon)|([Cc]anada)|([Cc]ayman\s+[Ii]slands)|([Cc]entral\s+[Aa]frican\s+[Rr]epublic)|([Cc]had)|([Cc]hile)|((([Tt]he\s+)?[Pp]eople['’]?s\s+[Rr]epublic\s+[Oo]f\s+)?[Cc]hina)|([Cc]hristmas\s+[Ii]sland)|([Cc]ocos\s+(.[Kk]eeling.\s+)?[Ii]slands)|((([Tt]he\s+)?[Rr]epublic\s+[Oo]f\s+)?[Cc]olombia)|([Cc]omoros)|([Dd]emocratic\s+[Rr]epublic\s+[Oo]f\s+([Tt]he\s+)?[Cc]ongo)|([Cc]ongo)|([Cc]ook\s+[Ii]slands)|([Cc]osta\s+[Rr]ica)|([Cc][ôo]te\s+d['’][Ii]voire)|([Cc]roatia)|([Cc]uba)|([Cc]yprus)|([Cc]zechia|[Cc]zech\s+[Rr]epublic)|((([Tt]he\s+)?[Kk]ingdom\s+[Oo]f\s+)?[Dd]enmark)|([Dd]jibouti)|([Dd]ominica)|([Dd]ominican\s+[Rr]epublic)|([Ee]cuador)|([Ee]gypt)|([Ee]l\s+[Ss]alvador)|([Ee]quatorial\s+[Gg]uinea)|([Ee]ritrea)|([Ee]stonia)|([Ee]thiopia)|(([Tt]he\s+)?[Ff]alkland\s+[Ii]slands(\s+.[Mm]alvinas.)?|([Ii]slas\s+)?[Mm]alvinas(\s+[Ii]slands)?)|([Ff]aroe\s+[Ii]slands)|([Ff]iji)|([Ff]inland)|([Ff]rance)|([Ff]rench\s+[Gg]uiana)|([Ff]rench\s+[Pp]olynesia)|([Ff]rench\s+[Ss]outhern\s+[Tt]erritories)|([Gg]abon)|([Gg]ambia)|([Gg]eorgia)|([Gg]ermany)|([Gg]hana)|([Gg]ibraltar)|([Gg]reece)|([Gg]reenland)|([Gg]renada)|([Gg]uadeloupe)|([Gg]uatemala)|([Gg]uernsey)|([Gg]uinea)|([Gg]uinea-[Bb]issau)|([Gg]uyana)|([Hh]aiti)|([Hh]eard\s+[Ii]sland\s+[Aa]nd\s+[Mm]cDonald\s+[Ii]slands)|(([Tt]he\s+)?[Hh]oly\s+[Ss]ee|[Vv]atican\s+[Cc]ity)|([Hh]onduras)|([Hh]ong\s+[Kk]ong)|([Hh]ungary)|([Ii]celand)|([Ii]ndia)|([Ii]ndonesia)|((([Tt]he\s+)?[Ii]slamic\s+[Rr]epublic\s+of\s+)?[Ii]ran)|([Ii]raq)|([Ii]reland)|([Ii]sle\s+[Oo]f\s+[Mm]an)|([Ii]srael)|([Ii]taly)|([Jj]amaica)|([Jj]apan)|([Jj]ersey)|([Jj]ordan)|([Kk]azakhstan)|([Kk]enya)|([Kk]iribati)|(([Nn]orth|[Dd]emocratic\s+[Pp]eople['’]?s\s+[Rr]epublic\s+[Oo]f)\s+[Kk]orea)|(([Ss]outh|[Rr]epublic\s+[Oo]f)\s+[Kk]orea)|([Kk]uwait)|([Kk]yrgyzstan)|([Ll]ao\s+[Pp]eople['’]?s\s+[Dd]emocratic\s+[Rr]epublic)|([Ll]atvia)|([Ll]ebanon)|([Ll]esotho)|([Ll]iberia)|((([Tt]he\s+)?[Ss]tate\s+[Oo]f\s+)?[Ll]ibya)|([Ll]iechtenstein)|([Ll]ithuania)|((([Tt]he\s+)?([Gg]rand\s+)?[Dd]uchy\s+[Oo]f\s+)?[Ll]uxembourg)|([Mm]aca[ou])|([Mm]adagascar)|([Mm]alawi)|([Mm]alaysia)|([Mm]aldives)|([Mm]ali)|([Mm]alta)|((([Tt]he\s+)?[Rr]epublic\s+[Oo]f\s+([Tt]he\s+)?)?[Mm]arshall\s+[Ii]slands)|([Mm]artinique)|([Mm]auritania)|([Mm]auritius)|([Mm]ayotte)|([Mm]exico|[Uu]nited\s+[Mm]exican\s+[Ss]tates)|((([Tt]he\s+)?[Ff]ederated\s+[Ss]tates\s+[Oo]f\s+)?[Mm]icronesia)|((([Tt]he\s+)?[Rr]epublic\s+[Oo]f\s+)?[Mm]oldova)|([Mm]onaco)|([Mm]ongolia)|([Mm]ontenegro)|([Mm]ontserrat)|([Mm]orocco)|([Mm]ozambique)|([Mm]yanmar)|([Nn]amibia)|([Nn]auru)|([Nn]epal)|([Nn]etherlands\s+[Aa]ntilles)|([Nn]etherlands)|([Nn]ew\s+[Cc]aledonia)|([Nn]ew\s+[Zz]ealand)|([Nn]icaragua)|([Nn]iger)|([Nn]igeria)|([Nn]iue)|([Nn]orfolk\s+[Ii]sland)|((([Tt]he\s+)?[Rr]epublic\s+[Oo]f\s+)?([Nn]orth\s+)?[Mm]acedonia)|([Nn]orthern\s+[Mm]ariana\s+[Ii]slands)|([Nn]orway)|([Oo]man)|([Pp]akistan)|([Pp]alau)|((([Tt]he\s+)?[Ss]tate\s+[Oo]f\s+)?[Pp]alestine)|([Pp]anama)|([Pp]apua\s+[Nn]ew\s+[Gg]uinea)|([Pp]araguay)|([Pp]eru)|([Pp]hilippines)|([Pp]itcairn)|([Pp]oland)|([Pp]ortugal)|([Qq]atar)|([Rr][ée]union)|([Rr]omania)|([Rr]ussian\s+[Ff]ederation)|([Rr]wanda)|([Ss]aint\s+[Bb]arth[ée]lemy)|([Ss]aint\s+[Hh]elena(,\s+[Aa]scension,?\s+[Aa]nd\s+[Tt]ristan(\s+[Dd]a\s+[Cc]unha)?)?)|([Ss]aint\s+[Kk]itts\s+[Aa]nd\s+[Nn]evis)|([Ss]aint\s+[Ll]ucia)|([Ss]aint\s+[Mm]artin)|([Ss]aint\s+[Pp]ierre\s+[Aa]nd\s+[Mm]iquelon)|([Ss]aint\s+[Vv]incent(\s+[Aa]nd\s+([Tt]he\s+)?[Gg]renadines)?)|([Ss]amoa)|([Ss]an\s+[Mm]arino)|([Ss]ao\s+[Tt]ome\s+[Aa]nd\s+[Pp]rincipe)|([Ss]audi\s+[Aa]rabia)|([Ss]enegal)|([Ss]erbia)|([Ss]eychelles)|([Ss]ierra\s+[Ll]eone)|([Ss]ingapore)|([Ss]lovakia)|([Ss]lovenia)|([Ss]olomon\s+[Ii]slands)|([Ss]omalia)|((([Tt]he\s+)?[Rr]epublic\s+[Oo]f\s+)?[Ss]outh\s+[Aa]frica)|([Ss]outh\s+[Gg]eorgia\s+[Aa]nd\s+([Tt]he\s+)?[Ss]outh\s+[Ss]andwich\s+[Ii]slands)|((([Tt]he\s+)?[Kk]ingdom\s+[Oo]f\s+)?[Ss]pain|[Ee]spa[ñn]a)|([Ss]ri\s+[Ll]anka)|([Ss]udan)|([Ss]uriname)|([Ss]valbard\s+[Aa]nd\s+[Jj]an\s+[Mm]ayen)|([Ss]waziland)|([Ss]weden)|([Ss]witzerland)|([Ss]yria(n\s+[Aa]rab\s+[Rr]epublic)?)|([Tt]aiwan(,?\s+[Pp]rovince\s+[Oo]f\s+[Cc]hina)?)|([Tt]ajikistan)|((([Tt]he\s+)?[Uu]nited\s+[Rr]epublic\s+[Oo]f\s+)?[Tt]anzania)|([Tt]hailand)|([Tt]imor-[Ll]este)|([Tt]ogo)|([Tt]okelau)|([Tt]onga)|([Tt]rinidad\s+[Aa]nd\s+[Tt]obago)|([Tt]unisia)|([Tt][uü]rk(ey|iye))|([Tt]urkmenistan)|([Tt]urks\s+[Aa]nd\s+[Cc]aicos\s+[Ii]slands)|([Tt]uvalu)|([Uu]ganda)|([Uu]kraine)|(UAE|[Uu]nited\s+[Aa]rab\s+[Ee]mirates)|(U[.]?K[.]?|[Bb]ritain|[Gg]reat\s+[BBb]ritain|[Uu]nited\s+[Kk]ingdom(\s+[Oo]f\s+[Gg]reat\s+[Bb]ritain\s+[Aa]nd\s+[Nn]orthern\s+[Ii]reland)?|[Ee]ngland(\s+[Aa]nd\s+[Ww]ales)?)|([Uu]nited\s+[Ss]tates\s+[Mm]inor\s+[Oo]utlying\s+[Ii]slands)|(U[.]?S[.]?A[.]?|[Uu]nited\s+[Ss]tates(\s+[Oo]f\s+[Aa]merica)?)|([Uu]ruguay)|([Uu]zbekistan)|([Vv]anuatu)|([Vv]enezuela)|([Vv]iet\s+[Nn]am)|([Bb]ritish\s+[Vv]irgin\s+[Ii]slands|[Vv]irgin\s+[Ii]slands,?\s+[Bb]ritish)|([Ww]allis\s+[Aa]nd\s+[Ff]utuna)|([Ww]estern\s+[Ss]ahara*)|([Yy]emen)|([Zz]ambia)|([Zz]imbabwe)|([Uu]nknown))[ \t\n\r]*$")
_EDGAR_PROVINCE_COUNTRY_CODES = ("B5", "GU", "PR", "2J", "VI", "A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "B0", "B2", "Y6", "B3", "B4", "B5", "B6", "B7", "1A", "B8", "B9", "C1", "1B", "1C", "C3", "C4", "1D", "C5", "C6", "C7", "C8", "1F", "C9", "D1", "G6", "D0", "D2", "D3", "1E", "B1", "D4", "D5", "D6", "D9", "E0", "X2", "E2", "E8", "E3", "E4", "Z4", "E9", "F0", "F2", "F3", "F4", "F6", "F7", "F8", "F9", "Y3", "G0", "G1", "G2", "L7", "1M", "G3", "G4", "2N", "G7", "1G", "G9", "G8", "H1", "H2", "H3", "H4", "1J", "1H", "H5", "H7", "H6", "H8", "H9", "I0", "I3", "I4", "2C", "I5", "I6", "2Q", "2M", "J0", "J1", "J3", "J4", "J5", "J6", "J8", "Y7", "J9", "S0", "K0", "K1", "K4", "X4", "K2", "K3", "K5", "K6", "K7", "K8", "K9", "L0", "L2", "Y8", "L3", "L6", "L8", "M0", "Y9", "M2", "1P", "M3", "J2", "M4", "M5", "M6", "1N", "M7", "1R", "M8", "M9", "N0", "N1", "N2", "1Q", "N4", "N5", "N6", "N7", "N8", "N9", "O0", "O1", "1T", "O2", "O3", "O4", "2P", "O5", "1K", "1S", "O9", "P0", "Z5", "P1", "P2", "P3", "E1", "T6", "P5", "P6", "P8", "P7", "1W", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "1U", "1V", "Q8", "P4", "R0", "1Y", "1X", "R1", "R2", "R4", "R5", "R6", "R8", "R9", "S1", "S3", "S4", "S5", "1Z", "S6", "Z0", "U8", "U7", "U9", "Z1", "V0", "V1", "Y0", "S8", "S9", "T0", "T1", "Z2", "T2", "T8", "U0", "2B", "2A", "D7", "U1", "T3", "1L", "U3", "F1", "V2", "V3", "L9", "V6", "V7", "V8", "V9", "F5", "2D", "W0", "W1", "Z3", "W2", "W3", "W4", "W5", "W6", "W8", "2E", "W7", "2G", "W9", "2H", "C0", "X0", "2J", "X1", "X3", "2K", "2L", "X5", "Q1", "D8", "X8", "U5", "T7", "Y4", "Y5", "XX")
_EXCHANGE_NAME_RE = regex_compile(r"^[ \t\n\r]*((([Tt]he\s+)?[Bb][Oo][Xx]\s+[Ee]xchange(,?\s+[Ll][Ll][Cc])?)|(([Tt]he\s+)?[Cc]boe\s+[Bb][Yy][Xx]\s+[Ee]xchange(,?\s+[Ii]nc[.]?)?)|(([Tt]he\s+)?[Cc]boe\s+[Bb][Zz][Xx]\s+[Ee]xchange(,?\s+[Ii]nc[.]?)?)|(([Tt]he\s+)?[Cc]boe\s+[Cc]2\s+[Ee]xchange(,?\s+[Ii]nc[.]?)?)|(([Tt]he\s+)?[Cc]boe\s+[Ee][Dd][Gg][Aa]\s+[Ee]xchange(,?\s+[Ii]nc[.]?)?)|(([Tt]he\s+)?[Cc]boe\s+[Ee][Dd][Gg][Xx]\s+[Ee]xchange(,?\s+[Ii]nc[.]?)?)|(([Tt]he\s+)?[Cc]boe\s+[Ee]xchange(,?\s+[Ii]nc[.]?)?)|(([Tt]he\s+)?[Cc]hicago\s+[Ss]tock\s+[Ee]xchange(,?\s+[Ii]nc[.]?)?)|(([Tt]he\s+)?[Ii]nvestors\s+[Ee]xchange(,?\s+[Ll][Ll][Cc])?)|(([Tt]he\s+)?[Mm]iami\s+[Ii]nternational\s+[Ss]ecurities\s+[Ee]xchange(,?\s+[Ll][Ll][Cc])?)|(([Tt]he\s+)?[Mm]IAX\s+[Pp]EARL(,?\s+[Ll][Ll][Cc])?)|(([Tt]he\s+)?[Nn][Aa][Ss][Dd][Aa][Qq]\s+[Bb][Xx](,?\s+[Ii]nc[.]?)?)|(([Tt]he\s+)?[Nn][Aa][Ss][Dd][Aa][Qq]\s+[Gg][Ee][Mm][Xx](,?\s+[Ll][Ll][Cc])?)|(([Tt]he\s+)?[Nn][Aa][Ss][Dd][Aa][Qq]\s+[Ii][Ss][Ee](,?\s+[Ll][Ll][Cc])?)|(([Tt]he\s+)?[Nn][Aa][Ss][Dd][Aa][Qq]\s+[Mm][Rr][Xx](,?\s+[Ll][Ll][Cc])?)|([Nn][Aa][Ss][Dd][Aa][Qq]\s+[Pp][Hh][Ll][Xx](,?\s+[Ll][Ll][Cc])?)|(([Tt]he\s+)?[Nn][Yy][Ss][Ee]|([Tt]he\s+)?[Nn]ew\s+[Yy]ork\s+[Ss]tock\s+[Ee]xchange(,?\s+[Ll][Ll][Cc])?)|(([Tt]he\s+)?[Nn][Yy][Ss][Ee]\s+[Aa]merican(,?\s+[Ll][Ll][Cc])?)|(([Tt]he\s+)?[Nn][Yy][Ss][Ee]\s+[Aa]rca(,?\s+[Ii]nc[.]?)?)|(([Tt]he\s+)?[Nn][Yy][Ss][Ee]\s+[Nn]ational(,?\s+[Ii]nc[.]?)?)|(([Tt]he\s+)?[Nn][Aa][Ss][Dd][Aa][Qq](\s+([Ss]tock|[Gg]lobal(\s+[Ss]elect)?)\s+[Mm]arket(,?\s+[Ll][Ll][Cc])?)?))[ \t\n\r]*$")
_EXCHANGE_CODES = ("BOX", "CboeBYX", "CboeBZX", "C2", "CboeEDGA", "CboeEDGX", "CBOE", "CHX", "IEX", "MIAX", "PEARL", "BX", "GEMX", "ISE", "MRX", "Phlx", "NYSE", "NYSEAMER", "NYSEArca", "NYSENAT", "NASDAQ")
_FILER_CATEGORIES = {
    "large accelerated filer": "Large Accelerated Filer",
    "accelerated filer": "Accelerated Filer",
    "non-accelerated filer": "Non-accelerated Filer",
    "smaller reporting company": "Smaller Reporting Company",
    "emerging growth company": "Emerging Growth Company",
}
_SEC_DECIMAL_RE = re.compile(
    r"^[ \t\n\r]*[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)[ \t\n\r]*$"
)
_SEC_NIL_RE = re.compile(r"^[ \t\n\r]*[Nn]il[ \t\n\r]*$")
# SEC-staff public-domain durwordsenPattern, copied verbatim (17 U.S.C. 105).
# https://github.com/Arelle/EDGAR/blob/master/transform/__init__.py
# Retrieved 2026-10-08; source SHA-256:
# 2296586f945ffd95ab37d3d4147c4e45f42ce4e5f397f61143e053208adefbf1
# Keep the reference capture groups: amounts are groups 2, 66, and 130.
# Validate the original source; replacing hyphens first changes the grammar.
_WORD_DURATION_RE = regex_compile(
    r"^[ \t\n\r]*((((([Oo]ne|[Tt](wo|hree|en|welve|hirteen)|[Ff](our(teen)?|ive|ifteen)|[Ss](ix(teen)?|even(teen)?)|[Ee](ight(een)?|leven)|[Nn]ine(teen)?)([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)[Hh]undred(([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)(and\s+)?(([Oo]ne|[Tt](wo|hree|en|welve|hirteen)|[Ff](our(teen)?|ive|ifteen)|[Ss](ix(teen)?|even(teen)?)|[Ee](ight(een)?|leven)|[Nn]ine(teen)?)|([Tt](wenty|hirty)|[Ff](orty|ifty)|[Ss](ixty|eventy)|[Ee]ighty|[Nn]inety)(([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)([Oo]ne|[Tt](wo|hree)|[Ff](our|ive)|[Ss](ix|even)|[Ee]ight|[Nn]ine))?))?)|(([Oo]ne|[Tt](wo|hree|en|welve|hirteen)|[Ff](our(teen)?|ive|ifteen)|[Ss](ix(teen)?|even(teen)?)|[Ee](ight(een)?|leven)|[Nn]ine(teen)?)|([Tt](wenty|hirty)|[Ff](orty|ifty)|[Ss](ixty|eventy)|[Ee]ighty|[Nn]inety)(([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)([Oo]ne|[Tt](wo|hree)|[Ff](our|ive)|[Ss](ix|even)|[Ee]ight|[Nn]ine))?))|[Zz]ero|[Nn]o|[0-9][0-9]{0,3})([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)[Yy]ears?(,?([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)(and\s+)?|$))?((((([Oo]ne|[Tt](wo|hree|en|welve|hirteen)|[Ff](our(teen)?|ive|ifteen)|[Ss](ix(teen)?|even(teen)?)|[Ee](ight(een)?|leven)|[Nn]ine(teen)?)([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)[Hh]undred(([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)(and\s+)?(([Oo]ne|[Tt](wo|hree|en|welve|hirteen)|[Ff](our(teen)?|ive|ifteen)|[Ss](ix(teen)?|even(teen)?)|[Ee](ight(een)?|leven)|[Nn]ine(teen)?)|([Tt](wenty|hirty)|[Ff](orty|ifty)|[Ss](ixty|eventy)|[Ee]ighty|[Nn]inety)(([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)([Oo]ne|[Tt](wo|hree)|[Ff](our|ive)|[Ss](ix|even)|[Ee]ight|[Nn]ine))?))?)|(([Oo]ne|[Tt](wo|hree|en|welve|hirteen)|[Ff](our(teen)?|ive|ifteen)|[Ss](ix(teen)?|even(teen)?)|[Ee](ight(een)?|leven)|[Nn]ine(teen)?)|([Tt](wenty|hirty)|[Ff](orty|ifty)|[Ss](ixty|eventy)|[Ee]ighty|[Nn]inety)(([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)([Oo]ne|[Tt](wo|hree)|[Ff](our|ive)|[Ss](ix|even)|[Ee]ight|[Nn]ine))?))|[Zz]ero|[Nn]o|[0-9][0-9]{0,3})([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)[Mm]onths?(,?([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)(and\s+)?|$))?((((([Oo]ne|[Tt](wo|hree|en|welve|hirteen)|[Ff](our(teen)?|ive|ifteen)|[Ss](ix(teen)?|even(teen)?)|[Ee](ight(een)?|leven)|[Nn]ine(teen)?)([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)[Hh]undred(([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)(and\s+)?(([Oo]ne|[Tt](wo|hree|en|welve|hirteen)|[Ff](our(teen)?|ive|ifteen)|[Ss](ix(teen)?|even(teen)?)|[Ee](ight(een)?|leven)|[Nn]ine(teen)?)|([Tt](wenty|hirty)|[Ff](orty|ifty)|[Ss](ixty|eventy)|[Ee]ighty|[Nn]inety)(([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)([Oo]ne|[Tt](wo|hree)|[Ff](our|ive)|[Ss](ix|even)|[Ee]ight|[Nn]ine))?))?)|(([Oo]ne|[Tt](wo|hree|en|welve|hirteen)|[Ff](our(teen)?|ive|ifteen)|[Ss](ix(teen)?|even(teen)?)|[Ee](ight(een)?|leven)|[Nn]ine(teen)?)|([Tt](wenty|hirty)|[Ff](orty|ifty)|[Ss](ixty|eventy)|[Ee]ighty|[Nn]inety)(([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)([Oo]ne|[Tt](wo|hree)|[Ff](our|ive)|[Ss](ix|even)|[Ee]ight|[Nn]ine))?))|[Zz]ero|[Nn]o|[0-9][0-9]{0,3})([\u058A\u05BE\u2010\u2011\u2012\u2013\u2014\u2015\uFE58\uFE63\uFF0D-]|\s+)[Dd]ays?)?[ \t\n\r]*$"
)
_WORD_DURATION_AMOUNT_GROUPS = ((2, "Y"), (66, "M"), (130, "D"))


def register_sec_inline_transforms() -> None:
    """Register the SEC EFM transforms for the installed Arelle process."""
    from arelle import FunctionIxt

    registry: dict[str, Callable[[str], str]] = {
        "durday": lambda value: _decimal_duration(value, "D"),
        "durweek": _week_duration,
        "durmonth": lambda value: _decimal_duration(value, "M"),
        "duryear": lambda value: _decimal_duration(value, "Y"),
        "durwordsen": _word_duration,
        "numwordsen": _number_words_transform,
        "countrynameen": _country_name,
        "stateprovnameen": _state_province_name,
        "edgarprovcountryen": _edgar_province_country_name,
        "exchnameen": _exchange_name,
        "entityfilercategoryen": lambda value: _lookup(value, _FILER_CATEGORIES, "filer category"),
        "boolballotbox": _bool_ballot_box,
    }
    FunctionIxt.ixtNamespaceFunctions.setdefault(SEC_TRANSFORM_NAMESPACE, {}).update(registry)


def _week_duration(value: str) -> str:
    """Convert SEC ``durweek`` lexical input to a days-only XSD duration.

    SEC's transform truncates fractional days after multiplying the absolute
    week magnitude by seven. The dedicated path keeps week-to-day conversion
    separate from ``durday``, whose fractional remainder spills into hours.
    """

    number, precision = _sec_duration_number(value, "week")
    with localcontext() as context:
        context.prec = precision
        days = int(abs(number) * 7)
    return _duration_value(None, None, days, None, _duration_sign(number))


def _decimal_duration(value: str, unit: str) -> str:
    unit_names = {"D": "day", "M": "month", "Y": "year"}
    try:
        unit_name = unit_names[unit]
    except KeyError as exc:
        raise ValueError(f"unsupported SEC duration unit: {unit}") from exc

    number, precision = _sec_duration_number(value, unit_name)
    sign = _duration_sign(number)
    with localcontext() as context:
        context.prec = precision
        magnitude = abs(number)
        whole = int(magnitude)
        if unit == "D":
            hours = int((magnitude - whole) * 24)
            return _duration_value(None, None, whole, hours, sign)
        if unit == "M":
            days = int((magnitude - whole) * Decimal("30.4375"))
            return _duration_value(None, whole, days, None, sign)

        raw_months = (magnitude - whole) * 12
        months = int(raw_months)
        days = int((raw_months - months) * Decimal("30.4375"))
        return _duration_value(whole, months, days, None, sign)


def _sec_duration_number(value: str, unit_name: str) -> tuple[Decimal, int]:
    """Parse the strict SEC decimal grammar with operation-safe precision."""
    if not isinstance(value, str) or _SEC_DECIMAL_RE.fullmatch(value) is None:
        raise ValueError(f"unsupported SEC {unit_name} duration: {value}")
    lexical = value.strip()
    digit_count = sum(character.isascii() and character.isdigit() for character in lexical)
    # Decimal construction is exact. The largest fixed multiplier (30.4375)
    # adds at most six coefficient digits; the extra margin also covers the
    # subtraction steps without depending on the caller's decimal context.
    return Decimal(lexical), max(28, digit_count + 8)


def _duration_sign(number: Decimal) -> str:
    return "-" if number < 0 else ""


def _duration_value(
    years: int | None,
    months: int | None,
    days: int | None,
    hours: int | None,
    sign: str,
) -> str:
    """Render components with SEC-staff ``durationValue`` zero semantics."""
    if all(component == 0 or component is None for component in (years, months, days, hours)):
        sign = ""
        found_zero = False
        if years is not None and years == 0:
            found_zero = True
        if months is not None and months == 0:
            if found_zero:
                months = None
            else:
                found_zero = True
        if days is not None and days == 0:
            if found_zero:
                days = None
            else:
                found_zero = True
        if hours is not None and hours == 0 and found_zero:
            hours = None

    output = sign + "P"
    if years is not None:
        output += f"{years}Y"
    if months is not None and (months != 0 or years is None):
        output += f"{months}M"
    if days is not None and (days != 0 or (years is None and months is None)):
        output += f"{days}D"
    if hours is not None and (hours != 0 or (years is None and months is None and days is None)):
        output += f"T{hours}H"
    return output


def _word_number(value: str) -> str:
    tokens = re.findall(r"[a-z]+|\d+", value.casefold())
    if not tokens:
        raise ValueError("empty English number")
    total = current = 0
    for token in tokens:
        if token == "and":
            continue
        if token.isdigit():
            current += int(token)
        elif token in _NUMBER_WORDS:
            current += _NUMBER_WORDS[token]
        elif token in _SCALES:
            current = max(1, current) * _SCALES[token]
            if _SCALES[token] >= 1000:
                total += current
                current = 0
        else:
            raise ValueError(f"unsupported English number token: {token}")
    return str(total + current)


def _number_words_transform(value: str) -> str:
    """Apply the SEC-only ``nil`` zero lexical before legacy word parsing."""
    if isinstance(value, str) and _SEC_NIL_RE.fullmatch(value):
        return "0"
    return _word_number(value)


def _word_duration(value: str) -> str:
    match = _WORD_DURATION_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None or not value.strip():
        raise ValueError(f"unsupported English duration: {value}")
    components = [
        (int(_word_number(match.group(group))), unit)
        for group, unit in _WORD_DURATION_AMOUNT_GROUPS
        if match.group(group) is not None
    ]
    result = "P" + "".join(f"{amount}{unit}" for amount, unit in components if amount)
    return result if result != "P" else "P0D"


def _lookup(value: str, mapping: dict[str, str], label: str) -> str:
    key = " ".join(value.casefold().split())
    if key not in mapping:
        raise ValueError(f"unsupported SEC {label}: {value}")
    return mapping[key]


def _country_name(value: str) -> str:
    return _coded_name(value, _COUNTRY_NAME_RE, _COUNTRY_CODES, "country")


def _state_province_name(value: str) -> str:
    return _coded_name(
        value,
        _STATE_PROVINCE_NAME_RE,
        _STATE_PROVINCE_CODES,
        "state/province",
    )


def _edgar_province_country_name(value: str) -> str:
    return _coded_name(
        value,
        _EDGAR_PROVINCE_COUNTRY_NAME_RE,
        _EDGAR_PROVINCE_COUNTRY_CODES,
        "EDGAR province/country",
    )


def _exchange_name(value: str) -> str:
    return _coded_name(value, _EXCHANGE_NAME_RE, _EXCHANGE_CODES, "exchange")


def _coded_name(value: str, pattern: Any, codes: tuple[str, ...], label: str) -> str:
    match = pattern.fullmatch(value) if isinstance(value, str) else None
    if match is None or not value.strip():
        raise ValueError(f"unsupported SEC {label}: {value}")
    index = _code_index(match)
    if index is None or index >= len(codes):
        raise ValueError(f"unsupported SEC {label}: {value}")
    return codes[index]


def _code_index(match: Any) -> int | None:
    """Return the SEC-staff code position for a matched name alternative."""
    groups = match.groups()
    for group_number in range(1, len(groups)):
        if groups[group_number] is None:
            continue
        parenthesis_number = 0
        for code_index, pattern_for_code in enumerate(match.re.pattern.split(")|")):
            in_character_class = False
            for character in pattern_for_code:
                if character == "[":
                    in_character_class = True
                elif character == "]":
                    in_character_class = False
                elif character == "(" and not in_character_class:
                    if parenthesis_number == group_number:
                        return code_index
                    parenthesis_number += 1
    return None


def _bool_ballot_box(value: str) -> str:
    """Translate the SEC EFM ballot-box glyphs to XML Schema booleans.

    The SEC ``boolballotbox`` transform accepts only the three ballot-box
    characters.  Reject every other input so an unexpected filing value remains
    a validation failure rather than being silently treated as ``false``.
    """
    normalized = value.strip()
    mapping = {"☐": "false", "☑": "true", "☒": "true"}
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported SEC bool ballot box: {value}") from exc
