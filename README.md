# TomTom Speeds Analysis — Corso Francia, Roma

Analisi della distribuzione delle velocita veicolari lungo **Corso di Francia** a Roma, basata sui dati **TomTom Speed Profiles** (1-15 Febbraio 2026).

Lo script Python genera un report HTML completo con grafici statici, mappe interattive Folium e tabelle di sintesi.

## Dati

I dati TomTom coprono quattro combinazioni di tipo giorno e direzione:

| Dataset | Direzione | Segmenti | Lunghezza | Periodo | Giorni esclusi |
|---------|-----------|----------|-----------|---------|----------------|
| Feriali | Centro | 59 | 2641 m | 01-15 Feb 2026 | Sab, Dom |
| Feriali | GRA | 47 | 2227 m | 01-15 Feb 2026 | Sab, Dom |
| Festivi | Centro | 57 | 2495 m | 01-15 Feb 2026 | Lun-Ven |
| Festivi | GRA | 53 | 2382 m | 01-15 Feb 2026 | Lun-Ven |

Ogni file GeoJSON contiene:
- **Feature 0**: metadati del percorso e riepiloghi orari a livello di rotta (velocita armoniche, percentili, tempi di percorrenza)
- **Feature 1-N**: segmenti stradali con geometria LineString e 24 serie orarie contenenti velocita media, mediana, armonica, deviazione standard, 19 percentili di velocita (5°-95°), campioni e tempi di percorrenza

### Struttura directory dati

```
Corso Francia_Feriali/
    Corso Francia_Dir. Centro_1.geojson
    Corso Francia_Dir. GRA_2.geojson
Corso Francia_Festivi/
    Corso Francia_Dir.Centro_1.geojson
    Corso Francia_Dir. GRA_2.geojson
```

## Installazione

```bash
pip install -r requirements.txt
```

Dipendenze principali: `pandas`, `numpy`, `matplotlib`, `geopandas`, `folium`, `shapely`, `branca`, `contextily`.

## Utilizzo

```bash
python analisi_velocita_corso_francia.py
```

Lo script genera tutti gli output nella cartella `output/`:

```
output/
    report_corso_francia.html    # Report HTML completo (~1.9 MB)
    dati_segmenti.csv            # Export CSV di tutti i dati segmento
    maps/
        progressive_centro.html          # Mappa progressive Dir. Centro
        progressive_gra.html             # Mappa progressive Dir. GRA
        v85_feriali_centro.html          # V85 medio Feriali Dir. Centro
        v85_feriali_gra.html             # V85 medio Feriali Dir. GRA
        v85_festivi_centro.html          # V85 medio Festivi Dir. Centro
        v85_festivi_gra.html             # V85 medio Festivi Dir. GRA
        std_feriali_centro.html          # Variabilita Feriali Dir. Centro
        std_feriali_gra.html             # Variabilita Feriali Dir. GRA
        night_v85_feriali_centro.html    # V85 notturno Feriali Dir. Centro
        night_v85_feriali_gra.html       # V85 notturno Feriali Dir. GRA
        top10_v85_feriali_centro.html    # Top 10 segmenti V85 Dir. Centro
        top10_v85_feriali_gra.html       # Top 10 segmenti V85 Dir. GRA
    static_maps/
        avg_speed_24h_feriali_centro.png     # Vel. media 24h Dir. Centro
        avg_speed_24h_feriali_gra.png        # Vel. media 24h Dir. GRA
        v85_24h_feriali_centro.png           # V85 24h Dir. Centro
        v85_24h_feriali_gra.png              # V85 24h Dir. GRA
        avg_speed_night_feriali_centro.png   # Vel. media notturna Dir. Centro
        avg_speed_night_feriali_gra.png      # Vel. media notturna Dir. GRA
        v85_night_feriali_centro.png         # V85 notturno Dir. Centro
        v85_night_feriali_gra.png            # V85 notturno Dir. GRA
```

Per consultare il report, aprire `output/report_corso_francia.html` in un browser.

## Contenuto del Report

Il report HTML e composto da 10 sezioni:

### 1. Introduzione e Metodologia
Descrizione dei dati, delle metriche utilizzate e del sistema di riferimento spaziale (progressive chilometriche). Include le mappe interattive delle progressive per entrambe le direzioni.

### 2. Panoramica dei Dati
Tabella riepilogativa con velocita media armonica (24h, punta AM/PM, notturna) per ciascun percorso. Tabella di superamento limiti pesata per km (non per numero di segmenti).

### 3. Profili Temporali di Velocita
- **Velocita media armonica per ora**: grafici separati per Feriali e Festivi, con le due direzioni sovrapposte
- **V85 medio per ora**: stessa struttura
- **Mappe di calore**: velocita per progressiva chilometrica (asse x) e ora (asse y), con celle proporzionali alla lunghezza effettiva dei segmenti (`pcolormesh`)

### 4. Superamento del Limite di Velocita
Percentuale dei km di percorso (non dei segmenti) con velocita > 50 km/h per ogni ora. Pannello sinistro: velocita media; pannello destro: V85.

### 5. Analisi V85 (85° Percentile)
- Profili spaziali del V85 nelle fasce orarie chiave (notte, punta AM, mezzogiorno, punta PM)
- Tabelle dei 10 tratti con V85 piu elevato, con numerazione progressiva e localizzazione in metri
- Mappe Folium che evidenziano i top 10 segmenti con marker numerati

### 6. Variabilita delle Velocita
- Mappe di calore della deviazione standard per progressiva e ora
- Profili spaziali: media giornaliera e massimo orario
- Spiegazione metodologica (dati forniti direttamente da TomTom)

### 7. Analisi delle Velocita Notturne
Grafici separati per Dir. Centro e Dir. GRA (progressive diverse = posizioni diverse):
- Istogrammi distribuzione velocita notte vs giorno
- Profili spaziali V85 e velocita media notturna

### 8. Confronto Feriali vs Festivi
Sovrapposizione dei profili orari feriali (linea continua) e festivi (linea tratteggiata) per velocita media e V85.

### 9. Mappe Interattive
8 mappe Folium embedded con segmenti colorati (peso linea = 10) e popup con statistiche dettagliate per ciascun segmento (progressiva, velocita media, V85, deviazione standard, limite, lunghezza).

### 10. Conclusioni e Raccomandazioni
Sintesi dei risultati principali e aree di attenzione.

## Mappe Statiche (`output/static_maps/`)

8 mappe PNG ad alta risoluzione (150 DPI) che mostrano la distribuzione delle velocita lungo il corridoio stradale in coordinate geografiche (lat/lon). Ogni segmento e colorato con una scala divergente verde-giallo-rosso centrata sul limite di 50 km/h:

| Mappa | Metrica | Ore | Direzione |
|-------|---------|-----|-----------|
| `avg_speed_24h_feriali_centro.png` | Velocita media | Tutte (0-23) | Centro |
| `avg_speed_24h_feriali_gra.png` | Velocita media | Tutte (0-23) | GRA |
| `v85_24h_feriali_centro.png` | V85 | Tutte (0-23) | Centro |
| `v85_24h_feriali_gra.png` | V85 | Tutte (0-23) | GRA |
| `avg_speed_night_feriali_centro.png` | Velocita media | Notturne (22-05) | Centro |
| `avg_speed_night_feriali_gra.png` | Velocita media | Notturne (22-05) | GRA |
| `v85_night_feriali_centro.png` | V85 | Notturne (22-05) | Centro |
| `v85_night_feriali_gra.png` | V85 | Notturne (22-05) | GRA |

Ciascuna mappa include:
- Segmenti stradali colorati per velocita (verde = sotto il limite, rosso = sopra)
- Marcatori progressivi ogni 500 m per localizzazione spaziale
- Indicatori di inizio (triangolo verde) e fine (triangolo rosso) del percorso
- Barra colori con linea tratteggiata al limite di 50 km/h
- Riepilogo statistico (media, max, min) nell'angolo inferiore

## Metodologia

### Metriche di velocita
- **Velocita media armonica (a livello di percorso)**: calcolata da TomTom come media armonica ponderata per la lunghezza di tutti i segmenti. Rappresentativa della velocita effettiva di percorrenza.
- **V85**: 85° percentile della distribuzione delle velocita osservate. Estratto dall'array di 19 percentili fornito da TomTom (indice 16, corrispondente a p85).
- **Deviazione standard**: dispersione delle velocita individuali dei veicoli, fornita direttamente da TomTom per ogni combinazione segmento/ora.

### Tasso di superamento pesato per km
Per ogni ora, il tasso di superamento e calcolato come:

```
% km che superano il limite = sum(lunghezza segmenti con V > 50) / lunghezza totale percorso * 100
```

Questo approccio evita la distorsione causata dalla diversa lunghezza dei segmenti (da ~15 m a ~120 m).

### Progressive chilometriche
I grafici spaziali utilizzano la progressiva chilometrica (distanza dall'inizio del percorso) sull'asse orizzontale. Le progressive sono specifiche per ciascuna direzione e sono visualizzabili sulle mappe interattive dedicate (`progressive_centro.html`, `progressive_gra.html`).

### Mappe di calore con pcolormesh
Le mappe di calore utilizzano `matplotlib.pcolormesh` con bordi x non uniformi, in modo che la larghezza di ogni cella sia proporzionale alla lunghezza effettiva del segmento corrispondente.

## Struttura dello Script

Lo script `analisi_velocita_corso_francia.py` e organizzato in 7 sezioni:

| Sezione | Contenuto |
|---------|-----------|
| 1 | Imports e configurazione (limiti, colori, fasce orarie) |
| 2 | Caricamento e parsing dei 4 file GeoJSON |
| 3 | Funzioni di analisi (superamento per km, statistiche per segmento) |
| 4 | Generazione grafici matplotlib (8 funzioni, ~16 figure) |
| 5 | Generazione mappe Folium (12 mappe interattive) |
| 6 | Assemblaggio report HTML con template inline |
| 7 | Funzione `main()` di orchestrazione |

## Parametri Configurabili

Modificabili all'inizio dello script:

| Parametro | Default | Descrizione |
|-----------|---------|-------------|
| `SPEED_LIMIT` | 50 | Limite di velocita (km/h) |
| `NIGHT_HOURS` | 0-5, 22-23 | Fascia notturna |
| `AM_PEAK` | 7-8 | Fascia punta mattina |
| `PM_PEAK` | 17-18 | Fascia punta sera |
| `MIDDAY` | 12-13 | Fascia mezzogiorno |

## Export CSV

Il file `output/dati_segmenti.csv` contiene tutti i dati a livello di segmento/ora con le seguenti colonne principali:

`day_type`, `direction`, `seg_idx`, `segmentId`, `streetName`, `frc`, `speedLimit`, `seg_distance`, `cum_dist_start`, `cum_dist_mid`, `cum_dist_end`, `hour`, `harm_avg_speed`, `avg_speed`, `median_speed`, `std_speed`, `avg_tt`, `median_tt`, `sample_size`, `p5`, `p15`, `p25`, `p50`, `p75`, `p85`, `p90`, `p95`
