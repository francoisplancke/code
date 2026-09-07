from flask import Flask, render_template, request
from search_interactive import CodeDuTravailSearch
import torch

app = Flask(__name__)

# Configuration
# On utilise le modèle optimisé pour le droit français et ta 1050 Ti
# MODEL_NAME = "maastrichtlawtech/lleqa-base" 
MODEL_NAME = "../paraphrase-multilingual-MiniLM-L12-v2"  
VECTORIZED_DIR = "./code_travail_vectorized"

# Initialisation globale du moteur de recherche
print("⚡ Initialisation du moteur de recherche...")
searcher = CodeDuTravailSearch(MODEL_NAME, VECTORIZED_DIR)

@app.route('/', methods=['GET', 'POST'])
def index():
    query = request.form.get('query', '')
    results = []
    
    if query:
        # On récupère les 10 meilleurs articles
        results = searcher.search(query, k=10)
    
    return render_template('index.html', query=query, results=results)

@app.route('/article/<article_id>')
def view_article(article_id):
    article = searcher.get_article_by_id(article_id)
    if not article:
        return "Article introuvable", 404
    
    # Bonus : Trouver des articles similaires à celui qu'on regarde
    # On prend le contenu de l'article comme requête de recherche
    similar_articles = searcher.search(article['contenu'], k=6)
    # On enlève le premier résultat car c'est l'article lui-même
    related = [a for a in similar_articles if a['id'] != article_id][:5]
    
    return render_template('article.html', article=article, related=related)

if __name__ == '__main__':
    app.run(debug=True, port=5000)