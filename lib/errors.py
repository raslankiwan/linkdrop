"""Translate extractor errors into actionable app responses."""
def download_error(exc):
    message=str(exc).replace('\x1b','')[:1500]
    lowered=message.lower().replace('’', "'")
    if '[youtube]' in lowered and any(part in lowered for part in ("confirm you're not a bot",'confirm you’re not a bot','sign in to confirm','use --cookies')):
        return {'error':'YouTube requires verification for this request. Try the local Mac app on your own connection. If needed, sign into YouTube in your browser and choose that browser under Browser session in the local app. This may help, but does not guarantee access.', 'code':'YOUTUBE_AUTH_REQUIRED'}
    return {'error':message,'code':'DOWNLOAD_FAILED'}
