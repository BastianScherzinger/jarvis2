import html as _html
import json
import logging
import threading
import urllib.request
import urllib.error
from django.shortcuts import render, redirect
from django.http import HttpResponsePermanentRedirect, HttpResponse
from django.contrib import messages
from django.conf import settings
from .forms import AnfrageForm

logger = logging.getLogger('apps.core')


def _build_html_email(name, leistung, email, telefon, adresse, zusatz_info):
    e = _html.escape
    site_name = e(getattr(settings, 'SITE_NAME', 'Firma'))
    telefon_str = e(telefon) if telefon else '<span style="color:#666;">–</span>'
    adresse_str = e(adresse) if adresse else '<span style="color:#666;">–</span>'

    if zusatz_info:
        zusatz_row = f"""
              <tr>
                <td style="padding:14px 0;">
                  <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Zusätzliche Informationen</div>
                  <div style="font-size:15px;color:#333;white-space:pre-wrap;line-height:1.6;">{e(zusatz_info)}</div>
                </td>
              </tr>"""
        adresse_border = 'border-bottom:1px solid #eee;'
    else:
        zusatz_row = ''
        adresse_border = ''

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:8px;overflow:hidden;border:1px solid #e0e0e0;">

        <tr>
          <td style="background:#0d2240;padding:28px 36px;text-align:center;">
            <div style="font-size:24px;font-weight:900;color:#fff;">{site_name}</div>
            <div style="font-size:12px;color:#e8960a;margin-top:6px;">Neue Kontaktanfrage</div>
          </td>
        </tr>

        <tr>
          <td style="background:#fff8ec;padding:14px 36px;border-left:4px solid #e8960a;">
            <span style="color:#e8960a;font-weight:bold;font-size:13px;">Neue Anfrage eingegangen</span>
          </td>
        </tr>

        <tr>
          <td style="padding:32px 36px;">
            <p style="margin:0 0 28px;font-size:20px;font-weight:bold;color:#111;">
              Anfrage von {e(name)}
            </p>

            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="padding:14px 0;border-bottom:1px solid #eee;">
                  <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Leistungsart</div>
                  <div style="font-size:16px;color:#111;font-weight:bold;">{e(leistung)}</div>
                </td>
              </tr>
              <tr>
                <td style="padding:14px 0;border-bottom:1px solid #eee;">
                  <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">E-Mail</div>
                  <div style="font-size:16px;">
                    <a href="mailto:{e(email)}" style="color:#0d2240;text-decoration:none;font-weight:bold;">{e(email)}</a>
                  </div>
                </td>
              </tr>
              <tr>
                <td style="padding:14px 0;border-bottom:1px solid #eee;">
                  <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Telefon</div>
                  <div style="font-size:16px;color:#333;">{telefon_str}</div>
                </td>
              </tr>
              <tr>
                <td style="padding:14px 0;{adresse_border}">
                  <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Adresse</div>
                  <div style="font-size:16px;color:#333;">{adresse_str}</div>
                </td>
              </tr>
              {zusatz_row}
            </table>

            <div style="margin-top:32px;text-align:center;">
              <a href="mailto:{e(email)}"
                 style="display:inline-block;background:#0d2240;color:#fff;font-size:15px;font-weight:bold;padding:14px 36px;border-radius:6px;text-decoration:none;">
                Jetzt antworten
              </a>
            </div>
          </td>
        </tr>

        <tr>
          <td style="background:#f9f9f9;padding:20px 36px;text-align:center;border-top:1px solid #eee;">
            <p style="margin:0;font-size:11px;color:#999;">Automatisch generiert von {site_name}</p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _send_anfrage_email(name, leistung, email, telefon, adresse, zusatz_info):
    api_key = getattr(settings, 'RESEND_API_KEY', '')
    if not api_key:
        logger.warning('Mail-Versand übersprungen: RESEND_API_KEY nicht gesetzt')
        return

    text = (
        f"Neue Anfrage über die Website:\n\n"
        f"Name:       {name}\n"
        f"Leistung:   {leistung}\n"
        f"E-Mail:     {email}\n"
        f"Telefon:    {telefon or '–'}\n"
        f"Adresse:    {adresse or '–'}\n\n"
        f"Zusatzinfo:\n{zusatz_info or '–'}"
    )
    html_body = _build_html_email(name, leistung, email, telefon, adresse, zusatz_info)

    payload = json.dumps({
        'from': settings.DEFAULT_FROM_EMAIL,
        'to': [settings.ADMIN_EMAIL],
        'subject': f'[{settings.SITE_NAME}] Neue Anfrage von {name}',
        'text': text,
        'html': html_body,
    }).encode('utf-8')

    req = urllib.request.Request(
        'https://api.resend.com/emails',
        data=payload,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'Django-Firma-Website/1.0',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode('utf-8')
            logger.info(
                f'Mail gesendet | an={settings.ADMIN_EMAIL} | '
                f'status={resp.status} | response={body}'
            )
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        logger.error(
            f'Resend HTTP-Fehler | status={e.code} | '
            f'from={settings.DEFAULT_FROM_EMAIL} | to={settings.ADMIN_EMAIL} | '
            f'response={body}'
        )
    except Exception as e:
        logger.error(
            f'Mail-Versand fehlgeschlagen | to={settings.ADMIN_EMAIL} | '
            f'fehler={type(e).__name__}: {e}'
        )


def home(request):
    return render(request, 'home.html')


def dienstleistungen(request):
    return render(request, 'dienstleistungen.html')


def ueber_uns(request):
    return render(request, 'ueber-uns.html')


def kontakt(request):
    return HttpResponsePermanentRedirect('/anfrage/')


def anfrage(request):
    if request.method == 'POST':
        if request.POST.get('website'):
            logger.warning(f'Honeypot ausgelöst von IP {request.META.get("REMOTE_ADDR")}')
            messages.success(request, 'Danke! Ihre Anfrage wurde gespeichert.')
            return redirect('core:anfrage')

        form = AnfrageForm(request.POST)
        if form.is_valid():
            obj = form.save()
            logger.info(
                f'Anfrage gespeichert: {obj.name} | '
                f'{obj.get_leistung_display()} | {obj.email}'
            )
            thread = threading.Thread(
                target=_send_anfrage_email,
                args=(
                    obj.name,
                    obj.get_leistung_display(),
                    obj.email,
                    obj.telefon,
                    obj.adresse,
                    obj.zusatz_info,
                ),
                daemon=True,
            )
            thread.start()
            messages.success(
                request,
                f'Danke, {obj.name}! Ihre Anfrage wurde gesendet. Wir melden uns bald.'
            )
            return redirect('core:anfrage')
    else:
        form = AnfrageForm()
    return render(request, 'anfrage.html', {'form': form})


def leistungen(request):
    return HttpResponsePermanentRedirect('/dienstleistungen/')


def impressum(request):
    return render(request, 'impressum.html')


def datenschutz(request):
    return render(request, 'datenschutz.html')


def agb(request):
    return render(request, 'agb.html')


def standorte(request):
    return render(request, 'standorte.html')


def robots_txt(request):
    site_url = getattr(settings, 'SITE_URL', '')
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin/\n"
        f"Sitemap: {site_url}/sitemap.xml\n"
    )
    return HttpResponse(content, content_type='text/plain; charset=utf-8')


def error_404(request, exception=None):
    return render(request, 'errors/404.html', status=404)


def error_500(request):
    return render(request, 'errors/500.html', status=500)
