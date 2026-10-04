class EuPostgresSearch:
 def __init__(self,conn): self.conn=conn
 def search(self,q,k=20):
  q=(q or '').strip()
  if not q:return []
  with self.conn.cursor() as c:
   if q[:1].isdigit() and ' ' not in q:
    c.execute('''SELECT p.provision_id,p.celex,p.kind,p.label,p.logical_path,p.text,a.title,a.act_type,0.0::float score FROM eu_provision p JOIN eu_act a USING(celex) WHERE upper(p.celex)=upper(%s) ORDER BY p.logical_path NULLS LAST,p.provision_id LIMIT %s''',(q,k))
   else:
    c.execute('''WITH q AS (SELECT websearch_to_tsquery('french',%s) query) SELECT p.provision_id,p.celex,p.kind,p.label,p.logical_path,p.text,a.title,a.act_type,ts_rank_cd(p.search_vector,q.query)::float score FROM eu_provision p JOIN eu_act a USING(celex),q WHERE p.search_vector @@ q.query ORDER BY score DESC,p.provision_id LIMIT %s''',(q,k))
   cols=[d.name for d in c.description];return [dict(zip(cols,r)) for r in c.fetchall()]
 def act(self,celex):
  with self.conn.cursor() as c:
   c.execute('SELECT celex,cellar_uuid,eli,act_type,title,document_date,legal_status,metadata FROM eu_act WHERE celex=%s',(celex,));r=c.fetchone()
   if not r:return None
   cols=[d.name for d in c.description];a=dict(zip(cols,r))
   c.execute('SELECT provision_id,celex,cellar_uuid,parent_id,kind,label,logical_path,text,metadata FROM eu_provision WHERE celex=%s ORDER BY logical_path NULLS LAST,provision_id',(celex,));cols=[d.name for d in c.description];a['provisions']=[dict(zip(cols,x)) for x in c.fetchall()];return a
