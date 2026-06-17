"""
data.py — Data download and management module.

Downloads daily OHLCV data for all NSE tickers from yfinance,
cleans it, and saves to /data/raw/ as CSV files.
"""

import os
import warnings
import pandas as pd
import yfinance as yf
from tqdm import tqdm

warnings.filterwarnings("ignore")

# ── Configuration ──────────────────────────────────────────────────────────────
TICKERS = [
    # ── Agri & Fertilizers ────────────────────────────────
    "BAJAJHIND.NS",  "BALRAMCHIN.NS",  "CHAMBLFERT.NS",
    "COROMANDEL.NS",  "GSFC.NS",  "KRBL.NS",
    "RENUKA.NS",  "TRIVENI.NS",  "UTTAMSUGAR.NS",
    # ── Auto Ancillaries ──────────────────────────────────
    "APOLLOTYRE.NS",  "BALKRISIND.NS",  "BHARATFORG.NS",
    "CEATLTD.NS",  "EXIDEIND.NS",  "GABRIEL.NS",
    "GRINDWELL.NS",  "JBMA.NS",  "LUMAXTECH.NS",
    "MOTHERSON.NS",  "SCHAEFFLER.NS",  "SUBROS.NS",
    "SUNDRMFAST.NS",  "SUPRAJIT.NS",  "UNOMINDA.NS",
    # ── Auto OEM ──────────────────────────────────────────
    "ASHOKLEY.NS",  "BAJAJ-AUTO.NS",  "EICHERMOT.NS",
    "ESCORTS.NS",  "HEROMOTOCO.NS",  "M&M.NS",
    "MARUTI.NS",  "TVSMOTOR.NS",
    # ── Aviation ──────────────────────────────────────────
    "GMRAIRPORT.NS",  "INDIGO.NS",
    # ── Banking - PSU ─────────────────────────────────────
    "BANKBARODA.NS",  "BANKINDIA.NS",  "CANBK.NS",
    "CENTRALBK.NS",  "INDIANB.NS",  "IOB.NS",
    "MAHABANK.NS",  "PNB.NS",  "SBIN.NS",
    "UNIONBANK.NS",
    # ── Banking - Private ─────────────────────────────────
    "AXISBANK.NS",  "DCBBANK.NS",  "FEDERALBNK.NS",
    "HDFCBANK.NS",  "ICICIBANK.NS",  "IDFCFIRSTB.NS",
    "INDUSINDBK.NS",  "KARURVYSYA.NS",  "KOTAKBANK.NS",
    "SOUTHBANK.NS",
    # ── Basic Materials ───────────────────────────────────
    "20MICRONS.NS",  "ANDHRAPAP.NS",  "ANDHRSUGAR.NS",
    "APCOTEXIND.NS",  "ARCHIDPLY.NS",  "ARIES.NS",
    "ASHAPURMIN.NS",  "ASTEC.NS",  "AVTNPL.NS",
    "BALAMINES.NS",  "BEPL.NS",  "BHAGERIA.NS",
    "BHAGYANGR.NS",  "BHARATWIRE.NS",  "BIRLACORPN.NS",
    "BODALCHEM.NS",  "CAMLINFINE.NS",  "CENTEXT.NS",
    "DCW.NS",  "DHANUKA.NS",  "EIDPARRY.NS",
    "ESTER.NS",  "FACT.NS",  "FCL.NS",
    "GENUSPAPER.NS",  "GOACARBON.NS",  "GOCLCORP.NS",
    "GREENPLY.NS",  "GULFOILLUB.NS",  "GULPOLY.NS",
    "HINDZINC.NS",  "HITECH.NS",  "HSCL.NS",
    "IFGLEXPOR.NS",  "IGPL.NS",  "IMFA.NS",
    "INDIACEM.NS",  "INDIAGLYCO.NS",  "INSECTICID.NS",
    "JAIBALAJI.NS",  "JAICORPLTD.NS",  "JAYNECOIND.NS",
    "JKLAKSHMI.NS",  "KAMDHENU.NS",  "KANORICHEM.NS",
    "KCP.NS",  "KESORAMIND.NS",  "KIRIINDUS.NS",
    "KOTHARIPET.NS",  "KRIDHANINF.NS",  "KSCL.NS",
    "KSL.NS",  "LINDEINDIA.NS",  "MAANALU.NS",
    "MADRASFERT.NS",  "MAGNUM.NS",  "MAITHANALL.NS",
    "MALUPAPER.NS",  "MANAKSTEEL.NS",  "MANALIPETC.NS",
    "MANINDS.NS",  "MSPL.NS",  "MUKANDLTD.NS",
    "NATHBIOGEN.NS",  "NCLIND.NS",  "NFL.NS",
    "ORIENTPPR.NS",  "PDMJEPAPER.NS",  "POLYPLEX.NS",
    "PRAKASH.NS",  "PRAKASHSTL.NS",  "PREMEXPLN.NS",
    "PRSMJOHNSN.NS",  "RALLIS.NS",  "RAMASTEEL.NS",
    "RCF.NS",  "RESPONIND.NS",  "RUCHIRA.NS",
    "SAGCEM.NS",  "SALSTEEL.NS",  "SESHAPAPER.NS",
    "SHARDACROP.NS",  "SHK.NS",  "SHREEPUSHK.NS",
    "SHYAMCENT.NS",  "SOTL.NS",  "SPIC.NS",
    "STARPAPER.NS",  "SUNDARAM.NS",  "SUNFLAG.NS",
    "SURYAROSNI.NS",  "TIRUMALCHM.NS",  "TNPETRO.NS",
    "USHAMART.NS",  "VASWANI.NS",  "VIDHIING.NS",
    "VIKASECO.NS",  "VINYLINDIA.NS",  "VISASTEEL.NS",
    "VISHNU.NS",  "VSSL.NS",  "WSTCSTPAPR.NS",
    "ZENITHSTL.NS",  "ZUARI.NS",
    # ── Capital Goods ─────────────────────────────────────
    "ABB.NS",  "AIAENG.NS",  "CARBORUNIV.NS",
    "CGPOWER.NS",  "CROMPTON.NS",  "CUMMINSIND.NS",
    "ELECON.NS",  "ELGIEQUIP.NS",  "GRAPHITE.NS",
    "GREAVESCOT.NS",  "HAVELLS.NS",  "KEI.NS",
    "KIRLOSBROS.NS",  "KIRLOSENG.NS",  "KSB.NS",
    "LT.NS",  "PRAJIND.NS",  "SHAKTIPUMP.NS",
    "SIEMENS.NS",  "TDPOWERSYS.NS",  "THERMAX.NS",
    "VGUARD.NS",  "VOLTAS.NS",
    # ── Capital Markets ───────────────────────────────────
    "MCX.NS",  "MOTILALOFS.NS",
    # ── Cement & Materials ────────────────────────────────
    "ACC.NS",  "AMBUJACEM.NS",  "ASTRAL.NS",
    "CENTURYPLY.NS",  "FINPIPE.NS",  "HEIDELBERG.NS",
    "JKCEMENT.NS",  "MANGLMCEM.NS",  "ORIENTCEM.NS",
    "RAMCOCEM.NS",  "SUPREMEIND.NS",  "ULTRACEMCO.NS",
    # ── Chemicals ─────────────────────────────────────────
    "AARTIIND.NS",  "ALKYLAMINE.NS",  "DEEPAKFERT.NS",
    "DEEPAKNTR.NS",  "GHCL.NS",  "GNFC.NS",
    "GUJALKALI.NS",  "HFCL.NS",  "HIKAL.NS",
    "NAVINFLUOR.NS",  "NOCIL.NS",  "PCBL.NS",
    "PIDILITIND.NS",  "PIIND.NS",  "SRF.NS",
    "SUDARSCHEM.NS",  "TATACHEM.NS",  "UPL.NS",
    "VINATIORGA.NS",
    # ── Communication Services ────────────────────────────
    "BAGFILMS.NS",  "BALAJITELE.NS",  "CINELINE.NS",
    "DBCORP.NS",  "DEN.NS",  "ENIL.NS",
    "GTL.NS",  "HMVL.NS",  "HTMEDIA.NS",
    "IMAGICAA.NS",  "JAGRAN.NS",  "JUSTDIAL.NS",
    "MTNL.NS",  "MUKTAARTS.NS",  "NAVNETEDUL.NS",
    "NDTV.NS",  "ONMOBILE.NS",  "PFOCUS.NS",
    "SAMBHAAV.NS",  "SAREGAMA.NS",  "SHEMAROO.NS",
    "TIPSMUSIC.NS",  "TTML.NS",  "TVTODAY.NS",
    "UFO.NS",
    # ── Consumer & FMCG ───────────────────────────────────
    "ABFRL.NS",  "BAJAJCON.NS",  "BAJAJELEC.NS",
    "BATAINDIA.NS",  "BLUESTARCO.NS",  "BRITANNIA.NS",
    "COLPAL.NS",  "DABUR.NS",  "EMAMILTD.NS",
    "GODFRYPHLP.NS",  "GODREJCP.NS",  "HINDUNILVR.NS",
    "ITC.NS",  "JUBLFOOD.NS",  "JYOTHYLAB.NS",
    "MARICO.NS",  "RADICO.NS",  "RELAXO.NS",
    "SHOPERSTOP.NS",  "SYMPHONY.NS",  "TATACONSUM.NS",
    "THANGAMAYL.NS",  "TITAN.NS",  "TRENT.NS",
    "VMART.NS",  "WHIRLPOOL.NS",
    # ── Consumer Cyclical ─────────────────────────────────
    "ADVANIHOTR.NS",  "AGI.NS",  "ALOKINDS.NS",
    "AMDIND.NS",  "ANTGRAPHIC.NS",  "ARCHIES.NS",
    "ASAHIINDIA.NS",  "ATULAUTO.NS",  "AUTOIND.NS",
    "BALKRISHNA.NS",  "BANCOINDIA.NS",  "BANSWRAS.NS",
    "BASML.NS",  "BHARATGEAR.NS",  "BOMDYEING.NS",
    "BYKE.NS",  "CANTABIL.NS",  "CCHHL.NS",
    "CELEBRITY.NS",  "CENTENKA.NS",  "CIEINDIA.NS",
    "COFFEEDAY.NS",  "COSMOFIRST.NS",  "DELTACORP.NS",
    "DONEAR.NS",  "ELGIRUBCO.NS",  "EMMBI.NS",
    "EPL.NS",  "FIEMIND.NS",  "FILATEX.NS",
    "FMGOETZE.NS",  "GANECOS.NS",  "GARFIBRES.NS",
    "GINNIFILA.NS",  "GOKEX.NS",  "GOLDIAM.NS",
    "GREENLAM.NS",  "HIMATSEIDE.NS",  "HLVLTD.NS",
    "HUHTAMAKI.NS",  "ICIL.NS",  "IFBIND.NS",
    "IGARASHI.NS",  "INDORAMA.NS",  "INDTERRAIN.NS",
    "JAMNAAUTO.NS",  "JAYBARMARU.NS",  "JINDALPOLY.NS",
    "JINDWORLD.NS",  "JKTYRE.NS",  "JTEKTINDIA.NS",
    "KAMATHOTEL.NS",  "KANANIIND.NS",  "KKCL.NS",
    "KPRMILL.NS",  "LAMBODHARA.NS",  "LAOPALA.NS",
    "LGBBROSLTD.NS",  "LIBERTSHOE.NS",  "LOVABLE.NS",
    "LUXIND.NS",  "LYPSAGEMS.NS",  "MAYURUNIQ.NS",
    "MENONBE.NS",  "MHRIL.NS",  "MINDACORP.NS",
    "MIRCELECTR.NS",  "MIRZAINT.NS",  "MOHITIND.NS",
    "MOLDTKPAC.NS",  "MONTECARLO.NS",  "MUNJALAU.NS",
    "MUNJALSHOW.NS",  "NAHARINDUS.NS",  "NDL.NS",
    "NITINSPIN.NS",  "NRBBEARING.NS",  "OMAXAUTO.NS",
    "ORICONENT.NS",  "ORIENTHOT.NS",  "PCJEWELLER.NS",
    "PEARLPOLY.NS",  "PGIL.NS",  "PILITA.NS",
    "PIONEEREMB.NS",  "PRECAM.NS",  "PRICOLLTD.NS",
    "REMSONSIND.NS",  "RGL.NS",  "RICOAUTO.NS",
    "ROHLTD.NS",  "RSWM.NS",  "RTNINDIA.NS",
    "RUBYMILLS.NS",  "RUPA.NS",  "RUSHIL.NS",
    "SANGAMIND.NS",  "SARLAPOLY.NS",  "SGL.NS",
    "SHIVAMAUTO.NS",  "SHREERAMA.NS",  "SIYSIL.NS",
    "SPECIALITY.NS",  "SPLIL.NS",  "SSWL.NS",
    "SUMEETINDS.NS",  "SUPERSPIN.NS",  "SUTLEJTEX.NS",
    "TAJGVK.NS",  "TALBROAUTO.NS",  "TBZ.NS",
    "TGBHOTELS.NS",  "THOMASCOOK.NS",  "TIMETECHNO.NS",
    "TPLPLASTEH.NS",  "TTKPRESTIG.NS",  "V2RETAIL.NS",
    "VAIBHAVGBL.NS",  "VARDHACRLC.NS",  "VGL.NS",
    "VIPCLOTHNG.NS",  "VIPIND.NS",  "VIVIDHA.NS",
    "VTL.NS",  "WONDERLA.NS",
    # ── Consumer Defensive ────────────────────────────────
    "ADFFOODS.NS",  "APTECHT.NS",  "AVANTIFEED.NS",
    "BBTC.NS",  "CCL.NS",  "COMPUSOFT.NS",
    "DALMIASUG.NS",  "DHAMPURSUG.NS",  "DWARKESH.NS",
    "ESSENTIA.NS",  "GAEL.NS",  "GLOBUSSPR.NS",
    "GMBREW.NS",  "GOKUL.NS",  "GOKULAGRO.NS",
    "HARRMALAYA.NS",  "HATSUN.NS",  "HERITGFOOD.NS",
    "JAYSREETEA.NS",  "JHS.NS",  "KCPSUGIND.NS",
    "KMSUGAR.NS",  "KOHINOOR.NS",  "KOTARISUG.NS",
    "MAWANASUG.NS",  "MCLEODRUSS.NS",  "NIITLTD.NS",
    "PARAGMILK.NS",  "PATANJALI.NS",  "RAJSREESUG.NS",
    "RAMANEWS.NS",  "RANASUG.NS",  "SAKHTISUG.NS",
    "SAKUMA.NS",  "SDBL.NS",  "SKMEGGPROD.NS",
    "TI.NS",  "UBL.NS",  "UGARSUGAR.NS",
    "VENKEYS.NS",  "VSTIND.NS",  "ZEELEARN.NS",
    "ZYDUSWELL.NS",
    # ── Defence & Railways ────────────────────────────────
    "BEL.NS",  "BEML.NS",  "BHEL.NS",
    "NBCC.NS",  "SOLARINDS.NS",
    # ── Diversified ───────────────────────────────────────
    "ADANIENT.NS",  "BAJAJHLDNG.NS",  "GRASIM.NS",
    "NAUKRI.NS",  "SUZLON.NS",  "TATAINVEST.NS",
    # ── Electronics & EMS ─────────────────────────────────
    "REDINGTON.NS",
    # ── Energy ────────────────────────────────────────────
    "CASTROLIND.NS",  "CHENNPETRO.NS",  "GMDCLTD.NS",
    "GULFPETRO.NS",  "HINDOILEXP.NS",  "HINDPETRO.NS",
    "JINDRILL.NS",  "OILCOUNTUB.NS",  "PANAMAPET.NS",
    "REFEX.NS",
    # ── Financial Services ────────────────────────────────
    "ALMONDZ.NS",  "BFINVEST.NS",  "BIRLAMONEY.NS",
    "CARERATING.NS",  "CGCL.NS",  "CHOLAHLDNG.NS",
    "CUB.NS",  "DELPHIFX.NS",  "DHANBANK.NS",
    "DIGISPICE.NS",  "DVL.NS",  "EDELWEISS.NS",
    "EMKAY.NS",  "GEOJITFSL.NS",  "GFLLIMITED.NS",
    "GICHSGFIN.NS",  "IDBI.NS",  "IFCI.NS",
    "INDBANK.NS",  "INDOTHAI.NS",  "INVENTURE.NS",
    "IVC.NS",  "J&KBANK.NS",  "JMFINANCIL.NS",
    "KTKBANK.NS",  "M&MFIN.NS",  "OSWALGREEN.NS",
    "PAISALO.NS",  "PFS.NS",  "PNBGILTS.NS",
    "POONAWALLA.NS",  "PSB.NS",  "RELIGARE.NS",
    "REPCOHOME.NS",  "SAMMAANCAP.NS",  "SATIN.NS",
    "SPCENET.NS",  "TFCILTD.NS",  "UCOBANK.NS",
    "VLSFINANCE.NS",  "YESBANK.NS",
    # ── Healthcare ────────────────────────────────────────
    "AARTIDRUGS.NS",  "ALPA.NS",  "AMRUTANJAN.NS",
    "APLLTD.NS",  "APOLLOHOSP.NS",  "BALPHARMA.NS",
    "BLISSGVS.NS",  "BROOKS.NS",  "CAPLIPOINT.NS",
    "DCAL.NS",  "FDC.NS",  "FORTIS.NS",
    "GUFICBIO.NS",  "HCG.NS",  "INDOCO.NS",
    "INDRAMEDCO.NS",  "INDSWFTLAB.NS",  "IOLCP.NS",
    "JAGSNPHARM.NS",  "JUBLPHARMA.NS",  "KILITCH.NS",
    "KOPRAN.NS",  "LALPATHLAB.NS",  "LINCOLN.NS",
    "LYKALABS.NS",  "MARKSANS.NS",  "MOREPENLAB.NS",
    "NECLIFE.NS",  "NEULANDLAB.NS",  "NH.NS",
    "ORCHPHARMA.NS",  "PANACEABIO.NS",  "POLYMED.NS",
    "RPGLIFE.NS",  "SHILPAMED.NS",  "SPARC.NS",
    "STAR.NS",  "SUVEN.NS",  "SYNGENE.NS",
    "THEMISMED.NS",  "THYROCARE.NS",  "UNICHEMLAB.NS",
    "VIMTALABS.NS",  "VIVIMEDLAB.NS",  "WOCKPHARMA.NS",
    # ── Hospitality ───────────────────────────────────────
    "EIHOTEL.NS",  "INDHOTEL.NS",
    # ── IT - Large Cap ────────────────────────────────────
    "COFORGE.NS",  "HCLTECH.NS",  "INFY.NS",
    "MPHASIS.NS",  "OFSS.NS",  "PERSISTENT.NS",
    "TCS.NS",  "TECHM.NS",  "WIPRO.NS",
    # ── IT - Mid & Small ──────────────────────────────────
    "BSOFT.NS",  "CYIENT.NS",  "DATAMATICS.NS",
    "ECLERX.NS",  "INTELLECT.NS",  "MASTEK.NS",
    "RAMCOIND.NS",  "SONATSOFTW.NS",  "SUBEXLTD.NS",
    "TANLA.NS",  "TATAELXSI.NS",  "ZENSARTECH.NS",
    # ── Industrials ───────────────────────────────────────
    "ACE.NS",  "APARINDS.NS",  "AROGRANITE.NS",
    "ASIANTILES.NS",  "ATLANTAA.NS",  "AXISCADES.NS",
    "BALMLAWRIE.NS",  "BLKASHYAP.NS",  "BLS.NS",
    "CCCL.NS",  "CORDSCABLE.NS",  "DCM.NS",
    "DREDGECORP.NS",  "EKC.NS",  "ELECTCAST.NS",
    "ESSARSHPNG.NS",  "EVEREADY.NS",  "EVERESTIND.NS",
    "FINCABLES.NS",  "GENUSPOWER.NS",  "GESHIP.NS",
    "GRAVITA.NS",  "GVT&D.NS",  "HEG.NS",
    "HGS.NS",  "HILTON.NS",  "HIRECT.NS",
    "INDIANHUME.NS",  "JISLDVREQS.NS",  "JISLJALEQS.NS",
    "JWL.NS",  "JYOTISTRUC.NS",  "KABRAEXTRU.NS",
    "KAJARIACER.NS",  "KECL.NS",  "KNRCON.NS",
    "KOKUYOCMLN.NS",  "LINC.NS",  "LOKESHMACH.NS",
    "MADHUCON.NS",  "MANAKCOAT.NS",  "MANAKSIA.NS",
    "MANINFRA.NS",  "MBLINFRA.NS",  "MMTC.NS",
    "MOLDTECH.NS",  "MURUDCERA.NS",  "NAVKARCORP.NS",
    "NECCLTD.NS",  "NELCAST.NS",  "NITCO.NS",
    "NOIDATOLL.NS",  "OMINFRAL.NS",  "ORIENTALTL.NS",
    "PATELENG.NS",  "PATINTLOG.NS",  "PDSL.NS",
    "PENIND.NS",  "PITTIENG.NS",  "POKARNA.NS",
    "POWERMECH.NS",  "PRECWIRE.NS",  "PVP.NS",
    "RAMKY.NS",  "RHIM.NS",  "RIIL.NS",
    "RKFORGE.NS",  "ROSSELLIND.NS",  "RPPINFRA.NS",
    "RUCHINFRA.NS",  "SADBHIN.NS",  "SALZERELEC.NS",
    "SANGHVIMOV.NS",  "SEPC.NS",  "SHANTIGEAR.NS",
    "SIGIND.NS",  "SIMPLEXINF.NS",  "SKIPPER.NS",
    "SOMANYCERA.NS",  "SPMLINFRA.NS",  "STCINDIA.NS",
    "STERTOOLS.NS",  "SWANCORP.NS",  "TARIL.NS",
    "TECHNOE.NS",  "TEXMOPIPES.NS",  "TEXRAIL.NS",
    "TIMKEN.NS",  "TRF.NS",  "TRITURBINE.NS",
    "UNIVCABLES.NS",  "VASCONEQ.NS",  "VESUVIUS.NS",
    "VETO.NS",  "VISAKAIND.NS",  "VRLLOG.NS",
    "WABAG.NS",  "WALCHANNAG.NS",  "WELENT.NS",
    "WINDMACHIN.NS",  "ZENTEC.NS",  "ZUARIIND.NS",
    # ── Infrastructure ────────────────────────────────────
    "APLAPOLLO.NS",  "ASHOKA.NS",  "CONCOR.NS",
    "ENGINERSIN.NS",  "HCC.NS",  "IRB.NS",
    "JINDALSAW.NS",  "JKIL.NS",  "KEC.NS",
    "NCC.NS",  "PNCINFRA.NS",  "TITAGARH.NS",
    "WELCORP.NS",
    # ── Insurance ─────────────────────────────────────────
    "MFSL.NS",
    # ── Logistics ─────────────────────────────────────────
    "ADANIPORTS.NS",  "ALLCARGO.NS",  "GPPL.NS",
    "SCI.NS",  "SNOWMAN.NS",  "TCI.NS",
    # ── Metals & Mining ───────────────────────────────────
    "COALINDIA.NS",  "GALLANTT.NS",  "GPIL.NS",
    "HINDALCO.NS",  "HINDCOPPER.NS",  "JINDALSTEL.NS",
    "JSL.NS",  "JSWSTEEL.NS",  "MAHSEAMLES.NS",
    "MOIL.NS",  "NATIONALUM.NS",  "NAVA.NS",
    "NMDC.NS",  "RAIN.NS",  "SAIL.NS",
    "SARDAEN.NS",  "TATASTEEL.NS",  "VEDL.NS",
    # ── NBFC ──────────────────────────────────────────────
    "BAJAJFINSV.NS",  "BAJFINANCE.NS",  "CANFINHOME.NS",
    "CHOLAFIN.NS",  "IIFL.NS",  "LICHSGFIN.NS",
    "LTF.NS",  "MANAPPURAM.NS",  "MMFL.NS",
    "MUTHOOTFIN.NS",  "SHRIRAMFIN.NS",  "SUNDARMFIN.NS",
    # ── Oil & Gas ─────────────────────────────────────────
    "BPCL.NS",  "GAIL.NS",  "GUJGASLTD.NS",
    "IGL.NS",  "IOC.NS",  "MGL.NS",
    "MRPL.NS",  "OIL.NS",  "ONGC.NS",
    "PETRONET.NS",  "RELIANCE.NS",
    # ── Paints ────────────────────────────────────────────
    "ASIANPAINT.NS",  "BERGEPAINT.NS",  "KANSAINER.NS",
    "SHALPAINTS.NS",
    # ── Paper & Packaging ─────────────────────────────────
    "JKPAPER.NS",  "TNPL.NS",  "UFLEX.NS",
    # ── Pharma ────────────────────────────────────────────
    "AJANTPHARM.NS",  "BIOCON.NS",  "GLAXO.NS",
    "GLENMARK.NS",  "GRANULES.NS",  "JBCHEPHARM.NS",
    "NATCOPHARM.NS",  "SMSPHARMA.NS",
    # ── Pharma - Large Cap ────────────────────────────────
    "ALKEM.NS",  "AUROPHARMA.NS",  "CIPLA.NS",
    "DIVISLAB.NS",  "DRREDDY.NS",  "IPCALAB.NS",
    "LUPIN.NS",  "SUNPHARMA.NS",  "TORNTPHARM.NS",
    "ZYDUSLIFE.NS",
    # ── Power & Renewables ────────────────────────────────
    "ADANIPOWER.NS",  "CESC.NS",  "GIPCL.NS",
    "INOXWIND.NS",  "JPPOWER.NS",  "JSWENERGY.NS",
    "NHPC.NS",  "NTPC.NS",  "OLECTRA.NS",
    "PFC.NS",  "POWERGRID.NS",  "PTC.NS",
    "RECLTD.NS",  "RPOWER.NS",  "SJVN.NS",
    "TATAPOWER.NS",  "TORNTPOWER.NS",
    # ── Real Estate ───────────────────────────────────────
    "ABREL.NS",  "AJMERA.NS",  "ALEMBICLTD.NS",
    "AMJLAND.NS",  "ANANTRAJ.NS",  "ARVSMART.NS",
    "ASHIANA.NS",  "ASHIMASYN.NS",  "AURUM.NS",
    "BRIGADE.NS",  "COUNCODOS.NS",  "DBREALTY.NS",
    "DLF.NS",  "EMAMIREAL.NS",  "FMNL.NS",
    "GODREJIND.NS",  "GODREJPROP.NS",  "HUBTOWN.NS",
    "KOLTEPATIL.NS",  "LPDC.NS",  "MAHLIFE.NS",
    "NESCO.NS",  "NILAINFRA.NS",  "OBEROIRLTY.NS",
    "OMAXE.NS",  "PARSVNATH.NS",  "PENINLAND.NS",
    "PHOENIXLTD.NS",  "PRAENG.NS",  "PRESTIGE.NS",
    "PROZONER.NS",  "PTL.NS",  "PURVA.NS",
    "SOBHA.NS",  "SUNTECK.NS",  "TEXINFRA.NS",
    "UNITECH.NS",
    # ── Security Services ─────────────────────────────────
    "PRIMESECU.NS",
    # ── Technology ────────────────────────────────────────
    "63MOONS.NS",  "ADROITINFO.NS",  "ADSL.NS",
    "AKSHOPTFBR.NS",  "ALANKIT.NS",  "ASTRAMICRO.NS",
    "AURIONPRO.NS",  "BBOX.NS",  "BIRLACABLE.NS",
    "BPL.NS",  "CIGNITITEC.NS",  "CYBERTECH.NS",
    "DLINKINDIA.NS",  "FCSSOFT.NS",  "FSL.NS",
    "GENESYS.NS",  "GSS.NS",  "GTLINFRA.NS",
    "HCL-INSYS.NS",  "ITI.NS",  "KELLTONTEC.NS",
    "NELCO.NS",  "NUCLEUS.NS",  "ONWARDTEC.NS",
    "PARACABLES.NS",  "PGEL.NS",  "QUICKHEAL.NS",
    "RAMCOSYS.NS",  "RSSOFTWARE.NS",  "RSYSTEMS.NS",
    "SAKSOFT.NS",  "SECURKLOUD.NS",  "STLTECH.NS",
    "SURANASOL.NS",  "TRIGYN.NS",  "TVSELECT.NS",
    "VAKRANGEE.NS",  "WEBELSOLAR.NS",  "XCHANGING.NS",
    # ── Telecom & Media ───────────────────────────────────
    "BHARTIARTL.NS",  "DISHTV.NS",  "HATHWAY.NS",
    "IDEA.NS",  "INDUSTOWER.NS",  "NETWORK18.NS",
    "SUNTV.NS",  "TATACOMM.NS",  "ZEEL.NS",
    # ── Textiles ──────────────────────────────────────────
    "ARVIND.NS",  "DCMSHRIRAM.NS",  "KITEX.NS",
    "RAYMOND.NS",  "TRIDENT.NS",  "WELSPUNLIV.NS",
    # ── Utilities ─────────────────────────────────────────
    "DPSCLTD.NS",  "ENERGYDEV.NS",  "GREENPOWER.NS",
    "GSPL.NS",  "INDOWIND.NS",  "NLCINDIA.NS",
    "RTNPOWER.NS",  "SURANAT&P.NS",
]

NIFTY_TICKER   = "^NSEI"
START_DATE     = "2016-01-01"
END_DATE       = "2026-04-30"
MAX_MISSING_PCT = 0.05          # skip ticker if >5 % bars missing

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR  = os.path.join(BASE_DIR, "data", "raw")


# ── Helpers ────────────────────────────────────────────────────────────────────
def ensure_dirs():
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "results", "charts"), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "results"), exist_ok=True)


def _safe_name(ticker: str) -> str:
    """Convert ticker to a safe filename stem."""
    return ticker.replace("^", "IDX_").replace(".", "_")


# ── Core download function ─────────────────────────────────────────────────────
def download_ticker(ticker: str,
                    start: str = START_DATE,
                    end: str   = END_DATE,
                    interval: str = "1d") -> pd.DataFrame | None:
    """
    Download OHLCV data for a single ticker.
    Returns cleaned DataFrame or None if data quality fails.
    """
    try:
        raw = yf.download(
            ticker, start=start, end=end,
            interval=interval, auto_adjust=True,
            progress=False, actions=False,
        )
    except Exception as exc:
        print(f"  [ERROR] {ticker}: download exception — {exc}")
        return None

    if raw is None or raw.empty:
        print(f"  [WARN]  {ticker}: no data returned")
        return None

    # Flatten multi-level columns (happens when yfinance returns extra levels)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    # Keep standard OHLCV columns only
    needed = ["Open", "High", "Low", "Close", "Volume"]
    missing_cols = [c for c in needed if c not in raw.columns]
    if missing_cols:
        print(f"  [WARN]  {ticker}: missing columns {missing_cols}")
        return None

    df = raw[needed].copy()

    # ── Data-quality gate ──────────────────────────────────────────────────────
    total_rows   = len(df)
    n_nan        = df["Close"].isna().sum()
    missing_frac = n_nan / total_rows if total_rows > 0 else 1.0

    if missing_frac > MAX_MISSING_PCT:
        print(
            f"  [SKIP]  {ticker}: {missing_frac:.1%} missing bars "
            f"exceeds {MAX_MISSING_PCT:.0%} threshold — skipping"
        )
        return None

    # Forward-fill minor gaps, then drop any remaining NaN rows
    df = df.ffill().dropna()

    # Ensure index is DatetimeIndex (timezone-naive)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "Date"

    # Sanity: close must be positive
    df = df[df["Close"] > 0]

    n_filled = int(n_nan)
    print(
        f"  [OK]    {ticker}: {len(df):,} bars  "
        f"({n_filled} NaN rows forward-filled)"
    )
    return df


# ── Batch download ─────────────────────────────────────────────────────────────
def download_all_data(tickers=None, force_download: bool = False) -> dict:
    """
    Download (or load from cache) data for all tickers.
    Returns dict  { ticker: DataFrame }.
    """
    if tickers is None:
        tickers = TICKERS + [NIFTY_TICKER]

    ensure_dirs()
    data_dict: dict[str, pd.DataFrame] = {}

    print("\n" + "=" * 60)
    print("  STAGE 1 — Downloading Market Data")
    print("=" * 60)

    for ticker in tqdm(tickers, desc="Tickers", ncols=70):
        csv_path = os.path.join(RAW_DIR, f"{_safe_name(ticker)}.csv")

        if os.path.exists(csv_path) and not force_download:
            df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index).tz_localize(None)
            print(f"  [CACHE] {ticker}: loaded {len(df):,} bars from disk")
        else:
            df = download_ticker(ticker)
            if df is not None:
                df.to_csv(csv_path)

        if df is not None and not df.empty:
            data_dict[ticker] = df

    print(f"\n  Downloaded {len(data_dict)} / {len(tickers)} tickers successfully.")
    return data_dict


# ── Single-ticker loader ───────────────────────────────────────────────────────
def load_data(ticker: str) -> pd.DataFrame | None:
    """Load a single ticker from CSV cache."""
    csv_path = os.path.join(RAW_DIR, f"{_safe_name(ticker)}.csv")
    if not os.path.exists(csv_path):
        return None
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df
