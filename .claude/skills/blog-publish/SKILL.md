---
name: blog-publish
description: Processo padrão para publicar postagens no blog do site resultadosexponenciais.com.br. Use sempre que qualquer agente precisar criar ou publicar conteúdo no blog — Mako, Pixel, Quill, Bolt, ou qualquer outro. Garante publicação trilingue (pt-BR, es, en) via Directus.
user-invocable: true
triggers:
  - "publicar no blog"
  - "postar no site"
  - "criar postagem"
  - "novo artigo"
  - "blog post"
---

# Processo de Publicação do Blog RXP

## Regra Fundamental

**TODA postagem no site `resultadosexponenciais.com.br` DEVE:**
1. Ser criada nos **3 idiomas**: `pt-BR`, `es`, `en`
2. Ser publicada via **Directus CMS** (nunca editar arquivos `.tsx` diretamente)
3. Usar o mesmo `slug` base nos 3 idiomas (pode ser traduzido, mas deve ser consistente)

Violações dessa regra geram 404 para visitantes internacionais e quebram o SEO multilíngue.

---

## Onde Publicar

- **CMS:** `https://project.resultadosexponenciais.com.br`
- **Coleção:** `rxp_site_blog_posts`
- **URL pública:** `https://resultadosexponenciais.com.br/recursos/blog/{slug}` (pt-BR)
- **URL pública es:** `https://resultadosexponenciais.com.br/es/recursos/blog/{slug}`
- **URL pública en:** `https://resultadosexponenciais.com.br/en/recursos/blog/{slug}`

---

## Campos Obrigatórios por Registro

Cada postagem = 3 registros no Directus (um por locale):

| Campo | Tipo | Obrigatório | Notas |
|---|---|---|---|
| `locale` | string | Sim | `pt-BR`, `es` ou `en` |
| `title` | string | Sim | Título no idioma do registro |
| `slug` | string | Sim | Mesmo valor nos 3 locales (URL-friendly, kebab-case) |
| `content` | HTML/rich text | Sim | Conteúdo completo no idioma |
| `status` | enum | Sim | `draft` ou `published` |
| `published_at` | datetime | Sim se published | Data/hora de publicação |
| `category` | M2O | Recomendado | Vincular a `rxp_site_blog_categories` |
| `tags` | JSON | Recomendado | Array de strings |
| `reading_time` | integer | Recomendado | Minutos estimados de leitura |
| `seo_title` | string | Recomendado | Max 60 chars, keyword primário incluso |
| `seo_description` | string | Recomendado | Max 160 chars, compele o clique |

---

## Checklist de Publicação

```
[ ] 1. Redigir conteúdo em pt-BR
[ ] 2. Traduzir para es (espanhol)
[ ] 3. Traduzir para en (inglês)
[ ] 4. Criar registro pt-BR no Directus com locale=pt-BR
[ ] 5. Criar registro es no Directus com locale=es (mesmo slug)
[ ] 6. Criar registro en no Directus com locale=en (mesmo slug)
[ ] 7. Verificar URLs: /recursos/blog/{slug} + /es/recursos/blog/{slug} + /en/recursos/blog/{slug}
[ ] 8. Confirmar que todos os 3 retornam 200 (não 404)
[ ] 9. Verificar formatação: iframes YouTube, sumário (nav), headings com id
```

---

## Como Criar via API Directus

```bash
# Variáveis
DIRECTUS_URL="https://project.resultadosexponenciais.com.br"
TOKEN="<token-admin>"
SLUG="meu-artigo-exemplo"

# Criar registro pt-BR
curl -X POST "$DIRECTUS_URL/items/rxp_site_blog_posts" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "locale": "pt-BR",
    "title": "Título em Português",
    "slug": "'$SLUG'",
    "content": "<p>Conteúdo HTML aqui</p>",
    "status": "published",
    "published_at": "2026-06-22T18:00:00Z",
    "seo_title": "Título SEO | Resultados Exponenciais",
    "seo_description": "Descrição com até 160 chars"
  }'

# Repetir para locale=es e locale=en com o mesmo slug
```

---

## Conteúdo HTML — Boas Práticas

O campo `content` aceita HTML. O sanitizador do site (`sanitize-html.ts`) permite:

- Headings `<h2 id="ancora">`, `<h3 id="ancora">` — necessário para o sumário funcionar
- `<nav aria-label="...">` — para sumário/TOC no topo do artigo
- `<iframe src="https://www.youtube.com/embed/VIDEO_ID" ...>` — embeds de YouTube
- `<iframe src="https://player.vimeo.com/video/VIDEO_ID" ...>` — embeds de Vimeo
- Tags comuns: `<p>`, `<strong>`, `<em>`, `<ul>`, `<ol>`, `<li>`, `<blockquote>`, `<pre>`, `<code>`, `<img>`, `<a>`

**Proibido (será removido pelo sanitizador):**
- `<script>`, `<style>`, `<iframe>` apontando para domínios não whitelisted
- Atributos `on*` (onclick, onload, etc.)
- URLs com `javascript:` ou `vbscript:`

---

## Verificação Pós-Publicação

Após publicar, verificar os 3 URLs:

```bash
curl -sI https://resultadosexponenciais.com.br/recursos/blog/{slug} | grep HTTP
curl -sI https://resultadosexponenciais.com.br/es/recursos/blog/{slug} | grep HTTP
curl -sI https://resultadosexponenciais.com.br/en/recursos/blog/{slug} | grep HTTP
# Todos devem retornar HTTP/2 200
```

---

## Erros Comuns

| Erro | Causa | Solução |
|---|---|---|
| 404 em /es/ ou /en/ | Registro com esse locale não existe no Directus | Criar os 3 registros com o mesmo slug |
| Formatação quebrada | HTML com tags não permitidas | Usar apenas tags da lista acima |
| YouTube não aparece | iframe com domínio errado | Usar `https://www.youtube.com/embed/VIDEO_ID` |
| Sumário sem links | Headings sem atributo `id` | Adicionar `id` nos h2/h3: `<h2 id="secao-1">` |
| 500 no blog | `revalidate` ou `generateStaticParams` no page.tsx | Não adicionar ISR — rota é fully dynamic |

---

## Agentes que Usam Este Skill

- **Mako** — quando produzir conteúdo SEO/blog para o site
- **Pixel** — quando repurpose de social para artigo longo
- **Quill** — quando documentar caso de uso ou tutorial
- **Bolt** — quando criar páginas programaticamente
- **Qualquer agente** solicitado a "postar no site" ou "criar artigo"
