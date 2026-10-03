"""Static company names and sectors for the 129 stocks on the Premium list (used for search, filters and the sector heatmap).
Sectors are broad, display-only groups. A symbol missing here still works; it is shown under 'Other'."""

INFO: dict[str, tuple[str, str]] = {
    "RELIANCE": ("Reliance Industries", "Energy"), "TCS": ("Tata Consultancy Services", "IT"), "HDFCBANK": ("HDFC Bank", "Banks"),
    "ICICIBANK": ("ICICI Bank", "Banks"), "INFY": ("Infosys", "IT"), "HINDUNILVR": ("Hindustan Unilever", "FMCG"), "ITC": ("ITC", "FMCG"),
    "SBIN": ("State Bank of India", "Banks"), "BHARTIARTL": ("Bharti Airtel", "Telecom"), "KOTAKBANK": ("Kotak Mahindra Bank", "Banks"),
    "LT": ("Larsen & Toubro", "Capital Goods"), "AXISBANK": ("Axis Bank", "Banks"), "ASIANPAINT": ("Asian Paints", "Consumer"),
    "MARUTI": ("Maruti Suzuki", "Auto"), "SUNPHARMA": ("Sun Pharmaceutical", "Pharma"), "TITAN": ("Titan Company", "Consumer"),
    "ULTRACEMCO": ("UltraTech Cement", "Materials"), "BAJFINANCE": ("Bajaj Finance", "Financial Services"), "NESTLEIND": ("Nestle India", "FMCG"),
    "WIPRO": ("Wipro", "IT"), "HCLTECH": ("HCL Technologies", "IT"), "NTPC": ("NTPC", "Power"), "POWERGRID": ("Power Grid Corporation", "Power"),
    "ONGC": ("Oil & Natural Gas Corporation", "Energy"), "TATASTEEL": ("Tata Steel", "Metals"), "M&M": ("Mahindra & Mahindra", "Auto"),
    "TECHM": ("Tech Mahindra", "IT"), "JSWSTEEL": ("JSW Steel", "Metals"), "ADANIENT": ("Adani Enterprises", "Conglomerate"),
    "ADANIPORTS": ("Adani Ports and SEZ", "Infrastructure"), "COALINDIA": ("Coal India", "Energy"), "BAJAJFINSV": ("Bajaj Finserv", "Financial Services"),
    "DRREDDY": ("Dr. Reddy's Laboratories", "Pharma"), "CIPLA": ("Cipla", "Pharma"), "GRASIM": ("Grasim Industries", "Materials"),
    "HINDALCO": ("Hindalco Industries", "Metals"), "BRITANNIA": ("Britannia Industries", "FMCG"), "EICHERMOT": ("Eicher Motors", "Auto"),
    "APOLLOHOSP": ("Apollo Hospitals", "Healthcare"), "BPCL": ("Bharat Petroleum", "Energy"), "TATAMOTORS": ("Tata Motors", "Auto"),
    "INDUSINDBK": ("IndusInd Bank", "Banks"), "HEROMOTOCO": ("Hero MotoCorp", "Auto"), "DIVISLAB": ("Divi's Laboratories", "Pharma"),
    "SBILIFE": ("SBI Life Insurance", "Insurance"), "HDFCLIFE": ("HDFC Life Insurance", "Insurance"), "TRENT": ("Trent", "Consumer"),
    "BEL": ("Bharat Electronics", "Defence"), "SHRIRAMFIN": ("Shriram Finance", "Financial Services"), "BAJAJ-AUTO": ("Bajaj Auto", "Auto"),
    "TATACONSUM": ("Tata Consumer Products", "FMCG"), "ADANIGREEN": ("Adani Green Energy", "Power"), "ADANIPOWER": ("Adani Power", "Power"),
    "AMBUJACEM": ("Ambuja Cements", "Materials"), "BANKBARODA": ("Bank of Baroda", "Banks"), "BERGEPAINT": ("Berger Paints", "Consumer"),
    "BOSCHLTD": ("Bosch", "Auto"), "CANBK": ("Canara Bank", "Banks"), "CHOLAFIN": ("Cholamandalam Investment", "Financial Services"),
    "COLPAL": ("Colgate-Palmolive India", "FMCG"), "DLF": ("DLF", "Realty"), "DABUR": ("Dabur India", "FMCG"), "GAIL": ("GAIL (India)", "Energy"),
    "GODREJCP": ("Godrej Consumer Products", "FMCG"), "HAVELLS": ("Havells India", "Capital Goods"), "ICICIGI": ("ICICI Lombard General Insurance", "Insurance"),
    "ICICIPRULI": ("ICICI Prudential Life Insurance", "Insurance"), "INDIGO": ("InterGlobe Aviation (IndiGo)", "Infrastructure"), "IOC": ("Indian Oil Corporation", "Energy"),
    "IRCTC": ("IRCTC", "Infrastructure"), "JINDALSTEL": ("Jindal Steel & Power", "Metals"), "LICI": ("Life Insurance Corporation", "Insurance"),
    "LUPIN": ("Lupin", "Pharma"), "MARICO": ("Marico", "FMCG"), "MUTHOOTFIN": ("Muthoot Finance", "Financial Services"), "NAUKRI": ("Info Edge (Naukri)", "IT"),
    "PFC": ("Power Finance Corporation", "Financial Services"), "PIDILITIND": ("Pidilite Industries", "Materials"), "PNB": ("Punjab National Bank", "Banks"),
    "RECLTD": ("REC", "Financial Services"), "SIEMENS": ("Siemens", "Capital Goods"), "SRF": ("SRF", "Materials"), "TATAPOWER": ("Tata Power", "Power"),
    "TORNTPHARM": ("Torrent Pharmaceuticals", "Pharma"), "UNIONBANK": ("Union Bank of India", "Banks"), "VEDL": ("Vedanta", "Metals"),
    "ZYDUSLIFE": ("Zydus Lifesciences", "Pharma"), "HAL": ("Hindustan Aeronautics", "Defence"), "BHEL": ("Bharat Heavy Electricals", "Capital Goods"),
    "IDFCFIRSTB": ("IDFC First Bank", "Banks"), "YESBANK": ("Yes Bank", "Banks"), "MAXHEALTH": ("Max Healthcare", "Healthcare"),
    "POLYCAB": ("Polycab India", "Capital Goods"), "ABB": ("ABB India", "Capital Goods"), "TVSMOTOR": ("TVS Motor Company", "Auto"),
    "CGPOWER": ("CG Power and Industrial Solutions", "Capital Goods"), "PERSISTENT": ("Persistent Systems", "IT"), "LTIM": ("LTIMindtree", "IT"),
    "MPHASIS": ("Mphasis", "IT"), "COFORGE": ("Coforge", "IT"), "PAGEIND": ("Page Industries", "Consumer"), "ASHOKLEY": ("Ashok Leyland", "Auto"),
    "BALKRISIND": ("Balkrishna Industries", "Auto"), "BANDHANBNK": ("Bandhan Bank", "Banks"), "FEDERALBNK": ("Federal Bank", "Banks"),
    "AUBANK": ("AU Small Finance Bank", "Banks"), "IDEA": ("Vodafone Idea", "Telecom"), "NMDC": ("NMDC", "Metals"), "SAIL": ("Steel Authority of India", "Metals"),
    "NHPC": ("NHPC", "Power"), "OFSS": ("Oracle Financial Services Software", "IT"), "INDHOTEL": ("Indian Hotels Company", "Consumer"),
    "JUBLFOOD": ("Jubilant FoodWorks", "Consumer"), "MRF": ("MRF", "Auto"), "UPL": ("UPL", "Materials"), "ACC": ("ACC", "Materials"),
    "ALKEM": ("Alkem Laboratories", "Pharma"), "AUROPHARMA": ("Aurobindo Pharma", "Pharma"), "BIOCON": ("Biocon", "Pharma"),
    "CUMMINSIND": ("Cummins India", "Capital Goods"), "GMRAIRPORT": ("GMR Airports", "Infrastructure"), "HINDPETRO": ("Hindustan Petroleum", "Energy"),
    "IGL": ("Indraprastha Gas", "Energy"), "LODHA": ("Macrotech Developers (Lodha)", "Realty"), "OBEROIRLTY": ("Oberoi Realty", "Realty"),
    "PETRONET": ("Petronet LNG", "Energy"), "PIIND": ("PI Industries", "Materials"), "TIINDIA": ("Tube Investments of India", "Auto"), "VOLTAS": ("Voltas", "Consumer"),
}


def name_of(symbol: str) -> str:
    return INFO.get(symbol, (symbol, "Other"))[0]


def sector_of(symbol: str) -> str:
    return INFO.get(symbol, (symbol, "Other"))[1]


def sectors() -> list[str]:
    return sorted({sector for _, sector in INFO.values()})
