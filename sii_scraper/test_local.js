const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

async function run() {
    const rut = process.env.SII_RUT;
    const password = process.env.SII_PASSWORD;

    if (!rut || !password) {
        console.error("Please provide SII_RUT and SII_PASSWORD in your environment variables.");
        process.exit(1);
    }

    console.log(`Starting SII STEALTH scraper test for RUT: ${rut}...`);

    let browser;
    try {
        browser = await puppeteer.launch({
            headless: false,
            defaultViewport: null,
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });

        const page = await browser.newPage();

        // Hide webdriver traces manually just in case
        await page.evaluateOnNewDocument(() => {
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
        });

        console.log("Navigating to SII Login...");
        await page.goto('https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoRutClave.html?https://misiir.sii.cl/cgi_misii/siihome.cgi', { waitUntil: 'networkidle2' });

        console.log("Filling Login form...");
        await page.waitForSelector('#rutcntr', { visible: true });

        // Split RUT if needed or type full. Usually #rutcntr is the full body.
        const cleanRut = rut.replace(/\./g, '');
        const components = cleanRut.split('-');

        // Some SII forms use two boxes, some use one. 
        // Based on zeusr login, it's usually one box for body and one for DV if id is different.
        // Let's check for #dvcntr or similar.
        const rutInput = await page.$('#rutcntr');
        const dvInput = await page.$('#dvcntr');

        if (dvInput) {
            await page.type('#rutcntr', components[0]);
            await page.type('#dvcntr', components[1]);
        } else {
            await page.type('#rutcntr', cleanRut);
        }

        await page.type('#clave', password);
        await page.click('#bt_ingresar');

        console.log("Waiting for navigation after login...");
        await page.waitForNavigation({ waitUntil: 'networkidle2' });

        // Verify if we are in
        const content = await page.content();
        if (content.includes('Cerrar Sesión') || content.includes('Mi SII')) {
            console.log("✅ Login Successful!");
        } else {
            console.log("❌ Login potentially failed or still seeing rejection.");
            await page.screenshot({ path: 'login_error.png' });
        }

        // Navigate to Folios
        console.log("Navigating to Timbraje Electrónico...");
        await page.goto('https://palena.sii.cl/cvc_cgi/dte/of_solicita_folios', { waitUntil: 'networkidle2' });

        // WAIT 5 seconds for user to see
        await new Promise(r => setTimeout(r, 5000));

        await page.screenshot({ path: 'sii_folios_page.png' });
        console.log("Screenshot saved to sii_folios_page.png");

        // TRY to find selectors
        const selectors = await page.evaluate(() => {
            const inputs = Array.from(document.querySelectorAll('input, select, button'));
            return inputs.map(i => ({
                tag: i.tagName,
                id: i.id,
                name: i.name,
                type: i.type,
                value: i.value
            })).filter(i => i.id || i.name);
        });

        console.log("Found Selectors on page:", JSON.stringify(selectors, null, 2));

    } catch (error) {
        console.error("Error during scraping:", error);
    } finally {
        if (browser) {
            // Keep browser open for 10s to let user inspect
            console.log("Closing in 10s...");
            await new Promise(r => setTimeout(r, 10000));
            await browser.close();
        }
    }
}

run();
