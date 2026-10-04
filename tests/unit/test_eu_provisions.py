import json,zipfile
from legal.eu.provision_tree import extract_xml,run
def ex(xml):return extract_xml(xml.encode(),"32000L0060","u","u/act.xml")[0]
def test_article_no_paragraph():
 r=ex("<ACT><ENACTING.TERMS><ARTICLE><TI.ART>Article 1</TI.ART><ALINEA><P>Hello</P></ALINEA></ARTICLE></ENACTING.TERMS></ACT>")
 assert [x["kind"] for x in r]==["ARTICLE","ALINEA"] and r[0]["article_label"]=="Article 1"
def test_nested_lists():
 r=ex("<ACT><ENACTING.TERMS><ARTICLE><TI.ART>2</TI.ART><PARAG><NO.PARAG>1.</NO.PARAG><ALINEA><LIST><ITEM><NP><NO.P>a)</NO.P><P>A<LIST><ITEM><NP><NO.P>i)</NO.P><TXT>B</TXT></NP></ITEM></LIST></P></NP></ITEM></LIST></ALINEA></PARAG></ARTICLE></ENACTING.TERMS></ACT>")
 li=[x for x in r if x["kind"]=="LIST_ITEM"];assert li[0]["list_path"]==["a)"] and li[1]["list_path"]==["a)","i)"]
def test_quote_article_not_promoted():
 r=ex("<ACT><ENACTING.TERMS><ARTICLE><TI.ART>1</TI.ART><ALINEA><P>X<QUOT.S><ARTICLE><TI.ART>99</TI.ART><PARAG><NO.PARAG>7</NO.PARAG></PARAG></ARTICLE></QUOT.S></P></ALINEA></ARTICLE></ENACTING.TERMS></ACT>")
 assert len([x for x in r if x["kind"]=="ARTICLE"])==1 and "99" not in r[0]["text"]
def test_divisions():
 r=ex("<ACT><ENACTING.TERMS><DIVISION><TITLE><TI>Chapitre I</TI></TITLE><DIVISION><TITLE><TI>Section 1</TI></TITLE><ARTICLE><TI.ART>3</TI.ART></ARTICLE></DIVISION></DIVISION></ENACTING.TERMS></ACT>")
 a=[x for x in r if x["kind"]=="ARTICLE"][0];assert a["division_path"]==["Chapitre I","Section 1"]
def test_annex_blocks():
 r=extract_xml(b"<ANNEX><TITLE><TI>Annex I</TI></TITLE><CONTENTS><P>A</P><TBL><CORPUS><ROW><CELL>B</CELL></ROW></CORPUS></TBL></CONTENTS></ANNEX>","x","u","a.xml")[0]
 assert [x["kind"] for x in r]==["ANNEX","ANNEX_BLOCK","ANNEX_BLOCK"]
def test_end_to_end(tmp_path):
 zp=tmp_path/"z.zip";ip=tmp_path/"id";inv=tmp_path/"inv";od=tmp_path/"o";mem="u/a.xml"
 with zipfile.ZipFile(zp,"w") as z:z.writestr(mem,"<ACT><ENACTING.TERMS><ARTICLE><TI.ART>1</TI.ART></ARTICLE></ENACTING.TERMS></ACT>")
 ip.write_text(json.dumps({"cellar_uuid":"u","celex":"32000L0060","status":"RESOLVED","act_type":"DIRECTIVE"})+"\n")
 inv.write_text(json.dumps({"cellar_uuid":"u","member":mem,"root_tag":"ACT"})+"\n")
 s=run(zp,ip,inv,od);assert s["directives_with_act_provisions"]==1 and s["parse_errors"]==0
