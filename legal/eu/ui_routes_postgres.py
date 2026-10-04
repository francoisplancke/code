from flask import abort,render_template,request
def register_eu_routes(app,eu,legi):
 @app.route('/eu')
 def eu_search():
  q=(request.args.get('query') or '').strip()
  try:k=max(1,min(int(request.args.get('k','20')),50))
  except ValueError:k=20
  return render_template('eu_search.html',query=q,results=eu.search(q,k) if q else [],k=k,active_corpus='eu')
 @app.route('/eu/texte/<celex>')
 def eu_text(celex):
  a=eu.act(celex)
  if not a:abort(404)
  return render_template('eu_text.html',act=a,active_corpus='eu')
 @app.route('/eu/texte/<celex>/matching')
 def eu_matching(celex):
  a=eu.act(celex)
  if not a:abort(404)
  pid=(request.args.get('provision') or '').strip();chosen=next((p for p in a['provisions'] if p['provision_id']==pid),None) if pid else None
  source=(chosen['text'] if chosen else '\n'.join(p['text'] for p in a['provisions'] if p['text']))[:30000]
  matches=legi.search(source,k=10,hybrid=True,lexical_weight=.25) if source else []
  return render_template('eu_matching.html',act=a,chosen=chosen,matches=matches,active_corpus='eu')
