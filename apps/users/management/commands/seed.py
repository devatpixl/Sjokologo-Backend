from django.core.management.base import BaseCommand
from django.utils.text import slugify


TRUFFLES = [
    {'id': 'pis', 'name': 'Pistasj', 'color': '#8A9A5B', 'note': 'Myk og nøtteaktig med en lett sødme'},
    {'id': 'has', 'name': 'Hasselnøtt', 'color': '#8B6914', 'note': 'Rik og karamellisert, klassisk sjokoladepar'},
    {'id': 'van', 'name': 'Vanilje', 'color': '#F3E5AB', 'note': 'Ren og kremete, tidløs eleganse'},
    {'id': 'bri', 'name': 'Bringebær', 'color': '#C0435A', 'note': 'Frisk og fruktig med en syrlig avslutning'},
    {'id': 'kar', 'name': 'Karamell', 'color': '#C9A35B', 'note': 'Smøraktig og dyp med et hint av salt'},
    {'id': 'lak', 'name': 'Lakris', 'color': '#2D2D2D', 'note': 'Dristig og urteaktig, typisk nordisk smak'},
    {'id': 'man', 'name': 'Mango', 'color': '#F5A623', 'note': 'Tropisk og syrlig, eksotisk kontrast'},
    {'id': 'pas', 'name': 'Pasjonsfrukt', 'color': '#E8763A', 'note': 'Intens og blomsteraktig med naturlig syre'},
]

PRODUCTS = [
    {
        'slug': 'liten-sjokoladeboks-klassisk',
        'name': 'Liten sjokoladeboks — Klassisk',
        'category': 'liten-sjokoladeboks',
        'size': '8 biter',
        'price': '249.00',
        'blurb': 'En nøye utvalgt samling av våre mest elskede smaker i en vakker liten eske. Perfekt som gave eller personlig nytelse.',
        'flavors': ['Pistasj', 'Hasselnøtt', 'Vanilje', 'Karamell'],
        'in_stock': True,
        'batch_number': '05',
        'batch_count': 45,
        'batch_total': 220,
    },
    {
        'slug': 'liten-sjokoladeboks-sommerlig',
        'name': 'Liten sjokoladeboks — Sommerlig',
        'category': 'liten-sjokoladeboks',
        'size': '8 biter',
        'price': '249.00',
        'blurb': 'Lyse og friske smaker inspirert av norske sommerdager. Bringebær, mango og pasjonsfrukt i perfekt harmoni.',
        'flavors': ['Bringebær', 'Mango', 'Pasjonsfrukt', 'Vanilje'],
        'in_stock': True,
        'batch_number': '05',
        'batch_count': 38,
        'batch_total': 220,
    },
    {
        'slug': 'liten-sjokoladeboks-nordisk',
        'name': 'Liten sjokoladeboks — Nordisk',
        'category': 'liten-sjokoladeboks',
        'size': '8 biter',
        'price': '249.00',
        'blurb': 'Dristige nordiske smaker med lakris og mørk karamell som bærebjelke. For den eventyrlige ganen.',
        'flavors': ['Lakris', 'Karamell', 'Hasselnøtt', 'Pistasj'],
        'in_stock': True,
        'batch_number': '05',
        'batch_count': 29,
        'batch_total': 220,
    },
    {
        'slug': 'stor-sjokoladeboks-klassisk',
        'name': 'Stor sjokoladeboks — Klassisk',
        'category': 'stor-sjokoladeboks',
        'size': '16 biter',
        'price': '449.00',
        'blurb': 'Vår fullstendige smaksreise i én eske — alle åtte smaker representert og nøye balansert for en komplett opplevelse.',
        'flavors': ['Pistasj', 'Hasselnøtt', 'Vanilje', 'Bringebær', 'Karamell', 'Lakris', 'Mango', 'Pasjonsfrukt'],
        'in_stock': True,
        'batch_number': '05',
        'batch_count': 52,
        'batch_total': 220,
    },
    {
        'slug': 'stor-sjokoladeboks-premium',
        'name': 'Stor sjokoladeboks — Premium',
        'category': 'stor-sjokoladeboks',
        'size': '16 biter',
        'price': '549.00',
        'blurb': 'Dobbel porsjon av våre mest populære smaker, pakket i eksklusiv svart boks med gullfolie. Vår mest prestisjefylte gave.',
        'flavors': ['Pistasj', 'Hasselnøtt', 'Vanilje', 'Karamell'],
        'in_stock': True,
        'batch_number': '05',
        'batch_count': 18,
        'batch_total': 220,
    },
    {
        'slug': 'signatur-sjokoladeboks',
        'name': 'Signatur sjokoladeboks',
        'category': 'stor-sjokoladeboks',
        'size': '24 biter',
        'price': '699.00',
        'blurb': 'Vår mest ambisiøse boks — 24 biter fordelt på samtlige smaker med personlig hilsen. Den ultimate sjokoladeopplevelsen.',
        'flavors': ['Pistasj', 'Hasselnøtt', 'Vanilje', 'Bringebær', 'Karamell', 'Lakris', 'Mango', 'Pasjonsfrukt'],
        'in_stock': True,
        'batch_number': '05',
        'batch_count': 12,
        'batch_total': 220,
    },
    {
        'slug': 'sjokoladebar-pistasj',
        'name': 'Sjokoladebar — Pistasj',
        'category': 'sjokoladebarer',
        'size': '80g',
        'price': '89.00',
        'blurb': 'Mørk sjokolade møter malt pistasj i en bar som feirer nøttens kompleksitet. Sprø tekstur, dyp smak.',
        'flavors': ['Pistasj'],
        'in_stock': True,
        'batch_number': '05',
        'batch_count': 95,
        'batch_total': 400,
    },
    {
        'slug': 'sjokoladebar-bringebaer',
        'name': 'Sjokoladebar — Bringebær',
        'category': 'sjokoladebarer',
        'size': '80g',
        'price': '89.00',
        'blurb': 'Hvit sjokolade med frysetørkede bringebær som gir en levende kontrast mellom sødme og syre.',
        'flavors': ['Bringebær'],
        'in_stock': True,
        'batch_number': '05',
        'batch_count': 78,
        'batch_total': 400,
    },
    {
        'slug': 'sjokoladebar-hasselnott',
        'name': 'Sjokoladebar — Hasselnøtt',
        'category': 'sjokoladebarer',
        'size': '80g',
        'price': '89.00',
        'blurb': 'Melkesjokolade med ristede hele hasselnøtter. Varm, karamellisert og uimotståelig.',
        'flavors': ['Hasselnøtt'],
        'in_stock': True,
        'batch_number': '05',
        'batch_count': 110,
        'batch_total': 400,
    },
    {
        'slug': 'sjokoladebar-lakris',
        'name': 'Sjokoladebar — Lakris',
        'category': 'sjokoladebarer',
        'size': '80g',
        'price': '89.00',
        'blurb': 'En dristig kombinasjon — mørk 72% sjokolade med saltet lakris. Nordisk karakter i sin reneste form.',
        'flavors': ['Lakris'],
        'in_stock': True,
        'batch_number': '05',
        'batch_count': 63,
        'batch_total': 400,
    },
    {
        'slug': 'sjokoladebar-karamell',
        'name': 'Sjokoladebar — Karamell',
        'category': 'sjokoladebarer',
        'size': '80g',
        'price': '89.00',
        'blurb': 'Flytende saltkaramell innbakt i melkesjokolade. Klassikeren som aldri skuffer.',
        'flavors': ['Karamell'],
        'in_stock': True,
        'batch_number': '05',
        'batch_count': 88,
        'batch_total': 400,
    },
    {
        'slug': 'custom-sjokoladeboks',
        'name': 'Bygg din egen eske',
        'category': 'liten-sjokoladeboks',
        'size': '8 biter',
        'price': '299.00',
        'price_min': '299.00',
        'price_max': '499.00',
        'blurb': 'Velg dine favorittsmaker og sett dine egne initialer på esken. En helt personlig sjokoladeopplevelse.',
        'flavors': ['Pistasj', 'Hasselnøtt', 'Vanilje', 'Bringebær', 'Karamell', 'Lakris', 'Mango', 'Pasjonsfrukt'],
        'in_stock': True,
        'batch_number': '05',
        'batch_count': 0,
        'batch_total': 999,
    },
    {
        'slug': 'sjokoladeboks-gavepakke',
        'name': 'Gavepakke — 3-pakning',
        'category': 'liten-sjokoladeboks',
        'size': '3 × 8 biter',
        'price': '699.00',
        'blurb': 'Tre ulike Liten sjokoladeboks — Klassisk, Sommerlig og Nordisk — i elegant gavepakking med håndskrevet kort.',
        'flavors': ['Pistasj', 'Hasselnøtt', 'Vanilje', 'Bringebær', 'Karamell', 'Lakris', 'Mango', 'Pasjonsfrukt'],
        'in_stock': True,
        'batch_number': '05',
        'batch_count': 22,
        'batch_total': 150,
    },
]

ARTICLES = [
    {
        'slug': 'sjokoladens-opprinnelse',
        'number': '001',
        'category': 'Opprinnelse',
        'title': 'Fra kakaotre til konfekt',
        'blurb': 'En reise gjennom tusenårene som formet verdens mest elskede råvare — fra mayaenes rituelle drikke til håndverkssjokolade.',
        'read_time': '6 min',
        'published_at': '12. januar MMXXVI',
        'is_featured': True,
        'content': [
            {'type': 'paragraph', 'text': 'Kakaotreet, Theobroma cacao, bærer et navn som betyr gudenes mat. I de tropiske regnskogene i Mellom-Amerika har det vokst i tusenvis av år, og fruktene har blitt dyrket og verdsatt av mayaene og aztekerne lenge før Europa oppdaget dem.'},
            {'type': 'heading', 'text': 'De første sjokoladedrikker'},
            {'type': 'paragraph', 'text': 'Mayaene tilberedte en bitter, krydret drikk av malte kakaobønner kalt xocolātl. Den ble konsumert kaldt, blandet med chilipepper og mais, og hadde en sentral plass i religiøse seremonier og som valuta.'},
            {'type': 'paragraph', 'text': 'Da spanske conquistadorer møtte aztekerne på 1500-tallet, tok de med seg kakaobønnene tilbake til Europa. Der ble drikken modifisert — sukker ble tilsatt, chilien fjernet — og den ble raskt en luksus forbeholdt den europeiske overklassen.'},
        ],
    },
    {
        'slug': 'haandverket-bak-konfekten',
        'number': '002',
        'category': 'Håndverk',
        'title': 'Håndverket bak hver bit',
        'blurb': 'Temperering, ganache og finishing — prosessene som skiller industriell sjokolade fra håndlaget konfekt som smelter annerledes i munnen.',
        'read_time': '8 min',
        'published_at': '3. februar MMXXVI',
        'is_featured': False,
        'content': [
            {'type': 'paragraph', 'text': 'Temperering er nøkkelen til sjokolade med den karakteristiske knekken og glansfull overflate. Prosessen innebærer å smelte sjokoladen, senke temperaturen kontrollert og deretter varme den opp igjen — alt for å forme de riktige kakaosmørskrystallene.'},
            {'type': 'heading', 'text': 'Form V-krystaller'},
            {'type': 'paragraph', 'text': 'Det er seks mulige krystallformer i kakaosmør. Bare Form V gir den stabile, blanke sjokoladen med god knekk. Temperering handler om å oppmuntre akkurat denne formen mens de andre avvises.'},
        ],
    },
    {
        'slug': 'smaksnoter-pistasj',
        'number': '003',
        'category': 'Smaksnoter',
        'title': 'Pistasj — nøttens dronning',
        'blurb': 'Hvorfor pistasj og sjokolade er en perfekt match, og hva som skjer på smaksplanet når disse to møtes i en konfekt av høy kvalitet.',
        'read_time': '4 min',
        'published_at': '18. februar MMXXVI',
        'is_featured': False,
        'content': [
            {'type': 'paragraph', 'text': 'Pistasjenøtten inneholder over 30 aromatiske forbindelser som komplementerer sjokoladens egen kompleksitet. Blant de viktigste er 2-acetyl-1-pyrrolin — det samme molekylet som gir basmatiris og popcorn sin karakteristiske duft.'},
            {'type': 'paragraph', 'text': 'Kombinert med mørk sjokolade som inneholder minst 70% kakao, skapes en harmoni der nøttens grønne, smøraktige noter møter sjokoladens fruktighet og lettere bitterhet.'},
        ],
    },
    {
        'slug': 'menneskene-bak-kakaoen',
        'number': '004',
        'category': 'Folk',
        'title': 'Menneskene bak kakaoen',
        'blurb': 'Møt familiene i Ecuador og Ghana som dyrker kakaobønnene vi bruker, og forstå hvorfor direkte handel betyr alt for kvaliteten.',
        'read_time': '10 min',
        'published_at': '7. mars MMXXVI',
        'is_featured': True,
        'content': [
            {'type': 'paragraph', 'text': 'Over 50 millioner mennesker er avhengige av kakaolandbruk for sin levebrød. Likevel er gjennomsnittskakaobonden blant de fattigste i verden. Det er denne paradokset som driver bevegelsen mot direkte handel og premiumsertifiseringer.'},
            {'type': 'heading', 'text': 'Familiegården i Guayas'},
            {'type': 'paragraph', 'text': 'I Guayas-provinsen i Ecuador driver familien Castillo en av de få gjenværende gårdene som dyrker Nacional-varianten — en heirloom-kakao som nesten forsvant på 1900-tallet. Bønnene deres regnes blant de fineste i verden og brukes av bare en håndfull sjokoladeprodusenter.'},
        ],
    },
]


class Command(BaseCommand):
    help = 'Seed the database with initial data'

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='Clear existing data before seeding')

    def handle(self, *args, **options):
        from apps.products.models import Product, Truffle
        from apps.users.models import CustomUser
        from apps.utils.models import Article

        if options['clear']:
            Product.objects.all().delete()
            Truffle.objects.all().delete()
            Article.objects.all().delete()
            CustomUser.objects.filter(email__in=['test@sjokoloko.no', 'admin@sjokoloko.no']).delete()
            self.stdout.write('Cleared existing seed data.')

        # Truffles
        created = 0
        for t in TRUFFLES:
            _, c = Truffle.objects.get_or_create(id=t['id'], defaults={'name': t['name'], 'color': t['color'], 'note': t['note']})
            if c:
                created += 1
        self.stdout.write(f'Truffles: {created} created, {len(TRUFFLES) - created} already existed.')

        # Products
        created = 0
        for p in PRODUCTS:
            defaults = {k: v for k, v in p.items() if k != 'slug'}
            _, c = Product.objects.get_or_create(slug=p['slug'], defaults=defaults)
            if c:
                created += 1
        self.stdout.write(f'Products: {created} created, {len(PRODUCTS) - created} already existed.')

        # Articles
        created = 0
        for a in ARTICLES:
            defaults = {k: v for k, v in a.items() if k != 'slug'}
            _, c = Article.objects.get_or_create(slug=a['slug'], defaults=defaults)
            if c:
                created += 1
        self.stdout.write(f'Articles: {created} created, {len(ARTICLES) - created} already existed.')

        # Test user
        if not CustomUser.objects.filter(email='test@sjokoloko.no').exists():
            CustomUser.objects.create_user(
                email='test@sjokoloko.no',
                name='Test Bruker',
                password='test1234',
            )
            self.stdout.write('Created test user: test@sjokoloko.no / test1234')
        else:
            self.stdout.write('Test user already exists.')

        # Admin user
        if not CustomUser.objects.filter(email='admin@sjokoloko.no').exists():
            CustomUser.objects.create_user(
                email='admin@sjokoloko.no',
                name='Admin',
                password='admin1234',
                is_admin=True,
                is_staff=True,
            )
            self.stdout.write('Created admin user: admin@sjokoloko.no / admin1234')
        else:
            self.stdout.write('Admin user already exists.')

        self.stdout.write(self.style.SUCCESS('Seed complete.'))
