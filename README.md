# agiletechexpert.com

Static landing page for **Agile Tech Expert** - white-label voice-broadcast and IVR reseller platform.

No build step. Plain HTML + CSS + JS. Fonts load from Google Fonts.

## Structure

```
index.html                       # the whole site
assets/bg.webp                   # desktop background (3008x1408)
assets/bg-mobile.webp            # mobile background (1000px wide)
deploy/nginx-agiletechexpert.conf
deploy/deploy.sh                 # git pull + nginx reload on the server
```

## 1. Push to GitHub (local machine)

```bash
cd agiletechexpert
git remote add origin git@github.com:Mkali10/agiletechexpert.git
git push -u origin main
```

## 2. First-time server setup (Ubuntu + nginx)

```bash
sudo git clone https://github.com/Mkali10/agiletechexpert.git /var/www/agiletechexpert
sudo chown -R www-data:www-data /var/www/agiletechexpert
sudo cp /var/www/agiletechexpert/deploy/nginx-agiletechexpert.conf /etc/nginx/sites-available/agiletechexpert.conf
sudo ln -s /etc/nginx/sites-available/agiletechexpert.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d agiletechexpert.com -d www.agiletechexpert.com
```

DNS: point `A` records for `agiletechexpert.com` and `www` to the server public IP before running certbot.

If the repo is private, clone with a deploy key or a GitHub token.

## 3. Every update

```bash
# local
git add -A && git commit -m "Update site" && git push

# server
sudo bash /var/www/agiletechexpert/deploy/deploy.sh
```
