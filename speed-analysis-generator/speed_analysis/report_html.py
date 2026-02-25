"""HTML report generator for speed analysis."""

import numpy as np
import pandas as pd

from .config import RoadConfig


def df_to_html_table(df):
    return df.to_html(index=False, classes="data-table", border=0)


def _iframe(fname, title):
    return (f'<h3>{title}</h3>'
            f'<iframe src="maps/{fname}" width="100%" height="500" '
            f'frameborder="0" style="border:1px solid #ddd;border-radius:4px;'
            f'margin-bottom:20px;"></iframe>')


def build_summary_tables(segments, summaries, seg_stats, config: RoadConfig):
    """Build all summary tables for the report."""
    tables = {}
    limit = config.speed_limit

    # Overview table
    overview_rows = []
    for dt in config.day_types:
        for dr in config.directions:
            label = config.labels.get((dt, dr), f"{dt} \u2192 {dr}")
            ss = summaries[(summaries["day_type"] == dt)
                           & (summaries["direction"] == dr)]
            if ss.empty:
                continue
            overview_rows.append({
                "Percorso": label,
                "Vel. Media 24h (km/h)": f"{ss['harm_avg_speed'].mean():.1f}",
                "Vel. Punta AM (km/h)":  f"{ss[ss['hour'].isin(config.am_peak)]['harm_avg_speed'].mean():.1f}",
                "Vel. Punta PM (km/h)":  f"{ss[ss['hour'].isin(config.pm_peak)]['harm_avg_speed'].mean():.1f}",
                "Vel. Notturna (km/h)":  f"{ss[ss['hour'].isin(config.night_hours)]['harm_avg_speed'].mean():.1f}",
            })
    tables["overview"] = pd.DataFrame(overview_rows)

    # Exceedance table
    exc_rows = []
    for dt in config.day_types:
        for dr in config.directions:
            label = config.labels.get((dt, dr), f"{dt} \u2192 {dr}")
            sub = segments[(segments["day_type"] == dt)
                           & (segments["direction"] == dr)]
            if sub.empty:
                continue
            total_m = sub.drop_duplicates("seg_idx")["seg_distance"].sum()

            def _pct(col):
                vals = []
                for h in range(24):
                    hs = sub[sub["hour"] == h]
                    vals.append(hs.loc[hs[col] > limit, "seg_distance"].sum()
                                / total_m * 100 if total_m > 0 else 0)
                return np.mean(vals)

            exc_rows.append({
                "Percorso": label,
                f"% km Vel.Media > {limit} (media 24h)": f"{_pct('avg_speed'):.1f}%",
                f"% km V85 > {limit} (media 24h)":       f"{_pct('p85'):.1f}%",
                "V85 massimo (km/h)":                    f"{sub['p85'].max():.0f}",
                "Vel. Media max (km/h)":                 f"{sub['avg_speed'].max():.1f}",
            })
    tables["exceedance"] = pd.DataFrame(exc_rows)

    # Top 10 per direction (using primary day_type)
    primary_dt = config.day_types[0] if config.day_types else "Feriali"
    for direction in config.directions:
        dir_slug = direction.lower().replace(" ", "_")
        st = seg_stats[
            (seg_stats["day_type"] == primary_dt)
            & (seg_stats["direction"] == direction)
        ].nlargest(10, "max_v85").reset_index(drop=True)
        if st.empty:
            continue
        tbl = pd.DataFrame({
            "#": range(1, len(st) + 1),
            "Progressiva (m)": st["cum_dist_start"].apply(lambda x: f"{x:.0f}"),
            "V85 Max (km/h)":  st["max_v85"].apply(lambda x: f"{x:.0f}"),
            "Vel. Media (km/h)": st["all_avg_speed"].apply(lambda x: f"{x:.1f}"),
            "Dev. Std. (km/h)":  st["all_std"].apply(lambda x: f"{x:.1f}"),
            "Limite (km/h)":     st["speedLimit"].apply(lambda x: f"{x:.0f}"),
        })
        tables[f"top_fast_{dir_slug}"] = tbl

    return tables


def generate_html_report(charts, map_files, tables, config: RoadConfig):
    """Generate the full HTML report."""
    road = config.road_name
    limit = config.speed_limit
    date_desc = config.date_description or "N/D"
    primary_dt = config.day_types[0] if config.day_types else "Feriali"
    dt_slug = primary_dt.lower().replace(" ", "_").replace(".", "")

    # Dynamic content
    heatmap_imgs = "".join(
        f'<h3>{lab}</h3><img src="data:image/png;base64,{b64}" style="max-width:100%;">'
        for lab, b64 in charts.get("heatmaps", {}).items()
    )
    v85_spatial_imgs = "".join(
        f'<h3>Dir. {d}</h3><img src="data:image/png;base64,{b64}" style="max-width:100%;">'
        for d, b64 in charts.get("v85_spatial", {}).items()
    )

    # Progressive iframes
    progressive_iframes = ""
    for dr in config.directions:
        dir_slug = dr.lower().replace(" ", "_")
        fname = f"progressive_{dir_slug}.html"
        if fname in map_files:
            progressive_iframes += _iframe(fname, f"Progressive \u2014 Dir. {dr}")

    # Top-10 sections
    top10_sections = ""
    for dr in config.directions:
        dir_slug = dr.lower().replace(" ", "_")
        table_key = f"top_fast_{dir_slug}"
        fname = f"top10_v85_{dt_slug}_{dir_slug}.html"
        if table_key in tables:
            top10_sections += f"<h3>Top 10 Tratti con V85 pi&ugrave; Elevato &mdash; Dir. {dr} ({primary_dt})</h3>\n"
            top10_sections += df_to_html_table(tables[table_key]) + "\n"
            if fname in map_files:
                top10_sections += _iframe(fname, f"Mappa Top 10 &mdash; Dir. {dr}")

    # Main map iframes
    main_map_iframes = ""
    for fname in sorted(map_files.keys()):
        if fname.startswith("progressive_") or fname.startswith("top10_"):
            continue
        # Build title from filename
        title = fname.replace(".html", "").replace("_", " ").title()
        main_map_iframes += _iframe(fname, title)

    # Day types list
    day_types_html = ""
    for dt in config.day_types:
        dirs_str = ", ".join(f"Direzione {d}" for d in config.directions)
        day_types_html += f"<li><strong>{dt}</strong> &mdash; {dirs_str}</li>\n"

    # Weekday/weekend chart
    comparison_section = ""
    if charts.get("weekday_weekend"):
        dt_label = " vs ".join(config.day_types[:2])
        comparison_section = f"""
<section id="comparison">
<h2>8. Confronto {dt_label}</h2>
<img src="data:image/png;base64,{charts['weekday_weekend']}" style="max-width:100%;">
<p class="chart-caption">Velocit&agrave; medie (sopra) e V85 (sotto) a confronto.</p>
</section>"""

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Analisi Velocit&agrave; &mdash; {road}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;line-height:1.6;
  color:#333;background:#f9f9f9;max-width:1200px;margin:0 auto;padding:20px}}
header{{background:linear-gradient(135deg,#1a237e,#283593);color:#fff;
  padding:40px;border-radius:8px;margin-bottom:30px;text-align:center}}
header h1{{font-size:2em;margin-bottom:8px}}
header h2{{font-size:1.3em;font-weight:300;opacity:.9}}
header p{{margin-top:12px;opacity:.8;font-size:.95em}}
nav{{background:#fff;padding:20px 30px;border-radius:8px;margin-bottom:30px;
  box-shadow:0 2px 4px rgba(0,0,0,.1)}}
nav h3{{margin-bottom:10px;color:#1a237e}}
nav ol{{padding-left:20px}} nav li{{margin-bottom:4px}}
nav a{{color:#1565c0;text-decoration:none}} nav a:hover{{text-decoration:underline}}
section{{background:#fff;padding:30px;border-radius:8px;margin-bottom:20px;
  box-shadow:0 2px 4px rgba(0,0,0,.1)}}
h2{{color:#1a237e;border-bottom:2px solid #e8eaf6;padding-bottom:8px;margin-bottom:20px}}
h3{{color:#283593;margin:20px 0 10px 0}}
img{{max-width:100%;height:auto;border-radius:4px;margin:10px 0}}
.data-table{{width:100%;border-collapse:collapse;margin:15px 0;font-size:.9em}}
.data-table th{{background:#1a237e;color:#fff;padding:10px 12px;text-align:left;font-weight:600}}
.data-table td{{padding:8px 12px;border-bottom:1px solid #e0e0e0}}
.data-table tr:nth-child(even){{background:#f5f5f5}}
.data-table tr:hover{{background:#e8eaf6}}
.insight-box{{background:#e8f5e9;border-left:4px solid #4caf50;padding:15px 20px;
  margin:15px 0;border-radius:0 4px 4px 0}}
.warning-box{{background:#fff3e0;border-left:4px solid #ff9800;padding:15px 20px;
  margin:15px 0;border-radius:0 4px 4px 0}}
.method-box{{background:#e3f2fd;border-left:4px solid #1976d2;padding:15px 20px;
  margin:15px 0;border-radius:0 4px 4px 0}}
.chart-caption{{text-align:center;font-style:italic;color:#666;font-size:.9em;
  margin-top:-5px;margin-bottom:20px}}
footer{{text-align:center;padding:20px;color:#999;font-size:.85em}}
</style>
</head>
<body>

<header>
<h1>Analisi della Distribuzione delle Velocit&agrave;</h1>
<h2>{road}</h2>
<p>Dati TomTom Speed Profiles &bull; Periodo: {date_desc}</p>
</header>

<nav>
<h3>Indice</h3>
<ol>
<li><a href="#intro">Introduzione e Metodologia</a></li>
<li><a href="#overview">Panoramica dei Dati</a></li>
<li><a href="#temporal">Profili Temporali di Velocit&agrave;</a></li>
<li><a href="#exceedance">Superamento del Limite di Velocit&agrave;</a></li>
<li><a href="#v85">Analisi V85 (85&deg; Percentile)</a></li>
<li><a href="#variability">Variabilit&agrave; delle Velocit&agrave;</a></li>
<li><a href="#night">Analisi delle Velocit&agrave; Notturne</a></li>
<li><a href="#comparison">Confronto tra Periodi</a></li>
<li><a href="#maps">Mappe Interattive</a></li>
<li><a href="#conclusions">Conclusioni e Raccomandazioni</a></li>
</ol>
</nav>

<!-- 1 INTRODUCTION -->
<section id="intro">
<h2>1. Introduzione e Metodologia</h2>
<p>Il presente report analizza la distribuzione delle velocit&agrave; veicolari lungo
<strong>{road}</strong>, utilizzando i dati TomTom Speed Profiles
relativi al periodo <strong>{date_desc}</strong>.</p>
<p>L&rsquo;analisi si basa sui seguenti dataset:</p>
<ul>
{day_types_html}
</ul>
<p>Metriche principali:</p>
<ul>
<li><strong>Velocit&agrave; media armonica</strong> &mdash; calcolata da TomTom come media armonica
    ponderata sulla lunghezza di tutti i segmenti, rappresentativa della velocit&agrave;
    effettiva di percorrenza.</li>
<li><strong>V85 (85&deg; percentile)</strong> &mdash; velocit&agrave; non superata dall&rsquo;85%
    dei veicoli. TomTom fornisce 19 percentili (dal 5&deg; al 95&deg;); il V85 corrisponde
    al 17&deg; valore dell&rsquo;array.</li>
<li><strong>Deviazione standard</strong> &mdash; dispersione delle velocit&agrave; individuali,
    fornita direttamente da TomTom per ogni segmento e ora.</li>
<li><strong>Tasso di superamento</strong> &mdash; percentuale dei <em>km di percorso</em>
    (non dei segmenti) con velocit&agrave; superiore al limite. Ogni segmento &egrave; pesato
    in proporzione alla propria lunghezza.</li>
</ul>
<p>Limite di velocit&agrave;: <strong>{limit} km/h</strong>.</p>

<h3>Riferimento Spaziale: Progressive Chilometriche</h3>
<p>Tutti i grafici spaziali utilizzano la <em>progressiva chilometrica</em>: la distanza
(in km) dall&rsquo;inizio del percorso. Le direzioni hanno punti di partenza diversi,
quindi le progressive sono specifiche per ciascuna direzione.</p>
{progressive_iframes}
</section>

<!-- 2 OVERVIEW -->
<section id="overview">
<h2>2. Panoramica dei Dati</h2>
<div class="method-box">
<strong>Nota metodologica:</strong> le velocit&agrave; sono le <em>medie armoniche a livello
di percorso</em> calcolate da TomTom. La media armonica pondera ogni segmento in base alla
propria lunghezza. I valori per le fasce orarie sono la media dei valori orari ricadenti nella fascia
(punta AM: 07&ndash;08, punta PM: 17&ndash;18, notturna: 22&ndash;05).
</div>
{df_to_html_table(tables['overview'])}

<h3>Riepilogo Superamento Limiti (pesato per km)</h3>
<div class="method-box">
<strong>Nota metodologica:</strong> per ogni ora si sommano le lunghezze dei segmenti con
velocit&agrave; superiore a {limit} km/h e si dividono per la lunghezza totale del percorso.
Il valore riportato &egrave; la media delle 24 ore.
</div>
{df_to_html_table(tables['exceedance'])}
</section>

<!-- 3 TEMPORAL -->
<section id="temporal">
<h2>3. Profili Temporali di Velocit&agrave;</h2>
<h3>Velocit&agrave; Media Armonica per Ora</h3>
<img src="data:image/png;base64,{charts['speed_by_hour']}">
<p class="chart-caption">Velocit&agrave; media armonica dell&rsquo;intero itinerario per ora.</p>

<h3>V85 Medio per Ora</h3>
<img src="data:image/png;base64,{charts['v85_by_hour']}">
<p class="chart-caption">85&deg; percentile mediato su tutti i segmenti per ora.</p>

<h3>Mappe di Calore: Velocit&agrave; per Progressiva e Ora</h3>
<p>L&rsquo;asse orizzontale riporta la progressiva chilometrica; la larghezza di ciascuna cella
&egrave; proporzionale alla lunghezza effettiva del segmento.</p>
{heatmap_imgs}
<p class="chart-caption">Verde = flusso libero (velocit&agrave; elevate);
rosso = congestione (velocit&agrave; ridotte).</p>
</section>

<!-- 4 EXCEEDANCE -->
<section id="exceedance">
<h2>4. Superamento del Limite di Velocit&agrave;</h2>
<p>Per ogni ora si calcola la percentuale della <em>lunghezza del percorso</em> (km) in cui
la velocit&agrave; supera {limit} km/h.</p>
<img src="data:image/png;base64,{charts['exceedance']}">
<p class="chart-caption">% dei km di percorso oltre il limite per ora.
Sinistra: velocit&agrave; media; destra: V85.</p>
</section>

<!-- 5 V85 -->
<section id="v85">
<h2>5. Analisi V85 (85&deg; Percentile)</h2>
<div class="method-box">
<strong>Metodologia V85:</strong><br>
Il V85 &egrave; la velocit&agrave; al di sotto della quale viaggia l&rsquo;85% dei veicoli.
TomTom fornisce per ogni segmento e ora un array di 19 percentili (5&deg;&ndash;95&deg;,
passo 5); il V85 &egrave; il 17&deg; valore (indice 16).
</div>

{v85_spatial_imgs}
<p class="chart-caption">Profilo spaziale V85 nelle diverse fasce orarie ({primary_dt}).</p>

{top10_sections}
</section>

<!-- 6 VARIABILITY -->
<section id="variability">
<h2>6. Variabilit&agrave; delle Velocit&agrave;</h2>
<div class="method-box">
<strong>Metodologia:</strong> la deviazione standard &egrave; fornita direttamente da TomTom
per ogni segmento e fascia oraria. Misura la dispersione delle velocit&agrave; individuali
attorno alla media.
</div>
<img src="data:image/png;base64,{charts['variability']}">
<p class="chart-caption">Mappe di calore (sopra) e profili spaziali (sotto) della deviazione
standard ({primary_dt}).</p>
</section>

<!-- 7 NIGHT -->
<section id="night">
<h2>7. Analisi delle Velocit&agrave; Notturne</h2>
<p>Le ore notturne (22:00&ndash;05:59) presentano volumi ridotti e velocit&agrave; pi&ugrave;
elevate.</p>
<img src="data:image/png;base64,{charts['night']}">
<p class="chart-caption">Riga superiore: distribuzione diurna vs notturna.
Riga inferiore: profilo spaziale V85 e velocit&agrave; media notturna ({primary_dt}).</p>
</section>

{comparison_section}

<!-- 9 MAPS -->
<section id="maps">
<h2>9. Mappe Interattive</h2>
<p>Cliccare su ciascun segmento per le statistiche dettagliate.</p>
{main_map_iframes}
</section>

<!-- 10 CONCLUSIONS -->
<section id="conclusions">
<h2>10. Conclusioni e Raccomandazioni</h2>
<div class="insight-box">
<strong>Risultati Principali:</strong>
<ul>
<li>L&rsquo;analisi copre l&rsquo;intero corridoio di {road} in tutte le direzioni</li>
<li>Il limite di {limit} km/h viene superato in una porzione significativa del percorso</li>
<li>Il V85 supera il limite in molte fasce orarie</li>
</ul>
</div>
<div class="warning-box">
<strong>Aree di Attenzione:</strong>
<ul>
<li>I tratti con elevata variabilit&agrave; di velocit&agrave; richiedono attenzione per la sicurezza</li>
<li>Le velocit&agrave; notturne suggeriscono la necessit&agrave; di misure di moderazione</li>
</ul>
</div>
<p><em>Report generato automaticamente dai dati TomTom Speed Profiles.
Si raccomanda un&rsquo;interpretazione contestualizzata da parte di tecnici qualificati.</em></p>
</section>

<footer>
<p>TomTom Speed Profiles &mdash; {road} &mdash; {date_desc}</p>
</footer>
</body></html>"""
    return html
