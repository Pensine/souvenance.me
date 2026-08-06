# Déployer le site (une fois, ~20 min)

Le site est statique et auto-suffisant (zéro build, zéro dépendance).

1. **Avant tout** : remplacer les placeholders dans tous les fichiers du site
   ```bash
   grep -rl 'souvenance.me\|Souvenance\|YOUR_LEMONSQUEEZY_URL' marketing/site/ | \
     xargs sed -i 's/souvenance.me/pensine.example/g; s/Souvenance/moncompte/g; s|YOUR_LEMONSQUEEZY_URL|https://…|g'
   ```
2. **Hébergement** : Cloudflare Pages (recommandé — gratuit, edge, analytics)
   ou GitHub Pages. Pointer le projet sur le dossier `site/` du repo public.
3. **CI** : copier `indexnow.yml` dans `.github/workflows/` du repo, créer le
   secret `INDEXNOW_KEY` (`openssl rand -hex 16`).
4. **Indexation** : Bing Webmaster Tools + Google Search Console (sitemap).
5. **Analytics** : snippet PostHog dans `index.html` si souhaité (mesurer
   quel annuaire convertit via `?ref=`).

Contenu :
- `index.html` — landing (schema.org SoftwareApplication + FAQPage)
- `vs-chatgpt-memory.html`, `vs-mem0.html` — pages comparatives (formats que
  les moteurs génératifs citent le plus)
- `guides/own-your-ai-memory.html` — guide longue traîne (schema.org HowTo)
- `llms.txt` — fiche produit pour les crawlers IA
- `robots.txt` (crawlers IA explicitement autorisés), `sitemap.xml`
