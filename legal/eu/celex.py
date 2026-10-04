from __future__ import annotations
import re
from urllib.parse import unquote
# Sector-3 work: 3 + YYYY + descriptor(1..3 letters) + number(4..6 digits),
# optionally old publication sequence "(NN)", optionally corrigendum "R(NN)".
SECTOR3=re.compile(r"^3(?P<year>\d{4})(?P<descriptor>[A-Z]{1,3})(?P<number>\d{4,6})(?P<sequence>\(\d{2}\))?(?P<corrigendum>R\(\d{2}\))?$",re.I)
CELEX_RESOURCE="/resource/celex/"
def decode_celex_resource(uri):
 if CELEX_RESOURCE not in uri:return None
 raw=uri.split(CELEX_RESOURCE,1)[1]
 # URI path aliases encode parentheses/slashes. Decode exactly once for identity parsing.
 return unquote(raw).upper()
def parse_sector3(value):
 value=unquote(value).upper()
 m=SECTOR3.fullmatch(value)
 if not m:return None
 d=m.groupdict();d["celex"]=value;d["year"]=int(d["year"])
 d["is_corrigendum"]=bool(d["corrigendum"])
 return d
def sector3_from_aliases(uris):
 vals=[]
 for uri in uris or []:
  c=decode_celex_resource(uri)
  if c and parse_sector3(c):vals.append(c)
 return sorted(set(vals))
