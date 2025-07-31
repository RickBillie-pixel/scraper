from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
import json
import re
import requests
from urllib.parse import urljoin, urlparse
import base64
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from datetime import datetime
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WebScraper:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        
    def __enter__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--no-zygote',
                '--disable-extensions',
                '--disable-web-security',
                '--disable-features=VizDisplayCompositor',
                '--user-agent=Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
            ]
        )
        self.context = self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
        )
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def scrape_website(self, url):
        """Complete website scraping"""
        try:
            page = self.context.new_page()
            
            # Track response for headers
            response_info = {}
            
            def handle_response(response):
                if response.url == url or response.url.rstrip('/') == url.rstrip('/'):
                    response_info['headers'] = dict(response.headers)
                    response_info['status'] = response.status
                    response_info['url'] = response.url
            
            page.on('response', handle_response)
            
            # Navigate to page and wait for load
            response = page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait extra time for JS rendering
            page.wait_for_timeout(3000)
            
            # Get basic page info
            final_url = page.url
            status_code = response.status if response else None
            
            # Get page content
            html_content = page.content()
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract all data
            data = {
                'url': url,
                'final_url': final_url,
                'status_code': status_code,
                'timestamp': datetime.now().isoformat(),
                'page_info': self._extract_page_info(page, soup),
                'meta_data': self._extract_meta_data(soup),
                'structured_data': self._extract_structured_data(soup),
                'social_media': self._extract_social_media_data(soup),
                'content': self._extract_content(soup),
                'technical': self._extract_technical_data(page, soup, response_info),
                'seo': self._extract_seo_data(soup),
                'links': self._extract_links(soup, final_url),
                'images': self._extract_images(soup, final_url),
                'robots_txt': self._get_robots_txt(final_url),
                'sitemap': self._get_sitemap_data(final_url),
                'screenshot': self._take_screenshot(page)
            }
            
            page.close()
            return data
            
        except Exception as e:
            logger.error(f"Error scraping {url}: {str(e)}")
            return {'error': str(e), 'url': url}

    def _extract_page_info(self, page, soup):
        """Extract basic page information"""
        title_elem = soup.find('title')
        return {
            'title': title_elem.text.strip() if title_elem else '',
            'url': page.url,
            'domain': urlparse(page.url).netloc,
            'path': urlparse(page.url).path,
            'query': urlparse(page.url).query,
            'fragment': urlparse(page.url).fragment,
            'protocol': urlparse(page.url).scheme
        }

    def _extract_meta_data(self, soup):
        """Extract all meta tags"""
        meta_data = {}
        
        # Standard meta tags
        for meta in soup.find_all('meta'):
            name = meta.get('name') or meta.get('property') or meta.get('http-equiv')
            content = meta.get('content')
            if name and content:
                meta_data[name] = content
        
        # Canonical URL
        canonical = soup.find('link', rel='canonical')
        if canonical:
            meta_data['canonical'] = canonical.get('href')
            
        # Alternative languages
        alt_langs = []
        for link in soup.find_all('link', rel='alternate'):
            if link.get('hreflang'):
                alt_langs.append({
                    'hreflang': link.get('hreflang'),
                    'href': link.get('href')
                })
        meta_data['alternate_languages'] = alt_langs
        
        # Favicon
        favicon_links = []
        for link in soup.find_all('link', rel=['icon', 'shortcut icon', 'apple-touch-icon']):
            favicon_links.append({
                'rel': link.get('rel'),
                'href': link.get('href'),
                'sizes': link.get('sizes'),
                'type': link.get('type')
            })
        meta_data['favicons'] = favicon_links
        
        return meta_data

    def _extract_structured_data(self, soup):
        """Extract structured data (JSON-LD, Microdata, RDFa)"""
        structured_data = {
            'json_ld': [],
            'microdata': [],
            'rdfa': []
        }
        
        # JSON-LD
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                if script.string:
                    data = json.loads(script.string)
                    structured_data['json_ld'].append(data)
            except json.JSONDecodeError:
                continue
        
        # Microdata
        for elem in soup.find_all(attrs={'itemscope': True}):
            item = self._extract_microdata_item(elem)
            if item:
                structured_data['microdata'].append(item)
        
        # RDFa (basic extraction)
        for elem in soup.find_all(attrs={'typeof': True}):
            rdfa_item = {
                'typeof': elem.get('typeof'),
                'properties': {}
            }
            for prop_elem in elem.find_all(attrs={'property': True}):
                prop = prop_elem.get('property')
                content = prop_elem.get('content') or prop_elem.text.strip()
                rdfa_item['properties'][prop] = content
            if rdfa_item['properties']:
                structured_data['rdfa'].append(rdfa_item)
            
        return structured_data

    def _extract_microdata_item(self, elem):
        """Extract microdata item"""
        item = {
            'type': elem.get('itemtype'),
            'properties': {}
        }
        
        for prop_elem in elem.find_all(attrs={'itemprop': True}):
            prop = prop_elem.get('itemprop')
            
            # Get content based on element type
            if prop_elem.name == 'meta':
                content = prop_elem.get('content')
            elif prop_elem.name in ['img', 'audio', 'video']:
                content = prop_elem.get('src')
            elif prop_elem.name == 'a':
                content = prop_elem.get('href')
            elif prop_elem.name == 'time':
                content = prop_elem.get('datetime') or prop_elem.text.strip()
            else:
                content = prop_elem.text.strip()
                
            if content:
                item['properties'][prop] = content
            
        return item if item['properties'] else None

    def _extract_social_media_data(self, soup):
        """Extract Open Graph, Twitter Cards, etc."""
        social_data = {
            'open_graph': {},
            'twitter_cards': {},
            'facebook': {},
            'linkedin': {}
        }
        
        for meta in soup.find_all('meta'):
            property_attr = meta.get('property', '')
            name_attr = meta.get('name', '')
            content = meta.get('content', '')
            
            if not content:
                continue
            
            # Open Graph
            if property_attr.startswith('og:'):
                social_data['open_graph'][property_attr[3:]] = content
            
            # Twitter Cards
            elif name_attr.startswith('twitter:'):
                social_data['twitter_cards'][name_attr[8:]] = content
            
            # Facebook specific
            elif property_attr.startswith('fb:'):
                social_data['facebook'][property_attr[3:]] = content
            
            # LinkedIn
            elif property_attr.startswith('linkedin:'):
                social_data['linkedin'][property_attr[9:]] = content
                
        return social_data

    def _extract_content(self, soup):
        """Extract page content structure"""
        content = {
            'headings': {},
            'paragraphs': [],
            'lists': [],
            'text_content': '',
            'word_count': 0,
            'reading_time': 0
        }
        
        # Headings
        for i in range(1, 7):
            headings = soup.find_all(f'h{i}')
            content['headings'][f'h{i}'] = [h.text.strip() for h in headings if h.text.strip()]
        
        # Paragraphs
        paragraphs = soup.find_all('p')
        content['paragraphs'] = [p.text.strip() for p in paragraphs if p.text.strip()]
        
        # Lists
        for ul in soup.find_all(['ul', 'ol']):
            list_items = [li.text.strip() for li in ul.find_all('li') if li.text.strip()]
            if list_items:
                content['lists'].append({
                    'type': ul.name,
                    'items': list_items
                })
        
        # Full text content (remove scripts and styles)
        for script in soup(["script", "style"]):
            script.decompose()
        text_content = soup.get_text()
        content['text_content'] = ' '.join(text_content.split())
        content['word_count'] = len(content['text_content'].split())
        content['reading_time'] = max(1, content['word_count'] // 200)  # Approx 200 words per minute
        
        return content

    def _extract_technical_data(self, page, soup, response_info):
        """Extract technical SEO data"""
        try:
            load_time = page.evaluate('performance.timing.loadEventEnd - performance.timing.navigationStart')
        except:
            load_time = None
            
        return {
            'load_time': load_time,
            'html_size': len(str(soup)),
            'response_headers': response_info.get('headers', {}),
            'security': {
                'https': page.url.startswith('https://'),
                'mixed_content': self._check_mixed_content(soup, page.url),
                'hsts_header': 'strict-transport-security' in response_info.get('headers', {})
            },
            'mobile_friendly': self._check_mobile_friendly(soup),
            'page_speed_insights': self._basic_performance_metrics(soup),
            'encoding': soup.original_encoding if hasattr(soup, 'original_encoding') else 'unknown'
        }

    def _check_mixed_content(self, soup, url):
        """Check for mixed content issues"""
        if not url.startswith('https://'):
            return []
            
        mixed_content = []
        for elem in soup.find_all(['img', 'script', 'link', 'iframe']):
            src = elem.get('src') or elem.get('href')
            if src and src.startswith('http://'):
                mixed_content.append(src)
        return mixed_content

    def _check_mobile_friendly(self, soup):
        """Basic mobile-friendly checks"""
        viewport = soup.find('meta', attrs={'name': 'viewport'})
        return {
            'has_viewport': bool(viewport),
            'viewport_content': viewport.get('content') if viewport else None,
            'responsive_images': len(soup.find_all('img', srcset=True)),
            'mobile_specific_meta': bool(soup.find('meta', attrs={'name': 'format-detection'}))
        }

    def _basic_performance_metrics(self, soup):
        """Basic performance metrics"""
        return {
            'images_without_alt': len(soup.find_all('img', alt=False)),
            'images_with_alt': len(soup.find_all('img', alt=True)),
            'external_scripts': len([s for s in soup.find_all('script', src=True) 
                                   if s.get('src', '').startswith(('http', '//'))]),
            'inline_scripts': len(soup.find_all('script', src=False)),
            'external_stylesheets': len([l for l in soup.find_all('link', rel='stylesheet') 
                                       if l.get('href', '').startswith(('http', '//'))]),
            'inline_styles': len(soup.find_all('style')),
            'total_links': len(soup.find_all('a', href=True)),
            'total_images': len(soup.find_all('img')),
            'forms': len(soup.find_all('form'))
        }

    def _extract_seo_data(self, soup):
        """Extract SEO-specific data"""
        title = soup.find('title')
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        
        seo_data = {
            'title_length': len(title.text) if title else 0,
            'meta_description_length': len(meta_desc.get('content', '')) if meta_desc else 0,
            'h1_count': len(soup.find_all('h1')),
            'h1_text': [h1.text.strip() for h1 in soup.find_all('h1')],
            'images_without_alt': len(soup.find_all('img', alt=False)),
            'internal_links_count': 0,  # Will be updated in _extract_links
            'external_links_count': 0,  # Will be updated in _extract_links
            'keywords_meta': soup.find('meta', attrs={'name': 'keywords'}),
            'robots_meta': soup.find('meta', attrs={'name': 'robots'})
        }
        
        if seo_data['keywords_meta']:
            seo_data['keywords_meta'] = seo_data['keywords_meta'].get('content', '')
        if seo_data['robots_meta']:
            seo_data['robots_meta'] = seo_data['robots_meta'].get('content', '')
            
        return seo_data

    def _extract_links(self, soup, base_url):
        """Extract all links"""
        links = {
            'internal': [],
            'external': [],
            'all': [],
            'email': [],
            'phone': []
        }
        
        base_domain = urlparse(base_url).netloc
        
        for link in soup.find_all('a', href=True):
            href = link.get('href')
            
            # Handle special links
            if href.startswith('mailto:'):
                links['email'].append({
                    'email': href[7:],
                    'text': link.text.strip()
                })
                continue
            elif href.startswith('tel:'):
                links['phone'].append({
                    'phone': href[4:],
                    'text': link.text.strip()
                })
                continue
            
            absolute_url = urljoin(base_url, href)
            link_domain = urlparse(absolute_url).netloc
            
            link_data = {
                'url': absolute_url,
                'text': link.text.strip(),
                'title': link.get('title', ''),
                'rel': link.get('rel', []),
                'target': link.get('target', ''),
                'nofollow': 'nofollow' in link.get('rel', [])
            }
            
            links['all'].append(link_data)
            
            if link_domain == base_domain or not link_domain:
                links['internal'].append(link_data)
            else:
                links['external'].append(link_data)
        
        return links

    def _extract_images(self, soup, base_url):
        """Extract all images"""
        images = []
        
        for img in soup.find_all('img'):
            src = img.get('src')
            if src:
                absolute_url = urljoin(base_url, src)
                images.append({
                    'src': absolute_url,
                    'alt': img.get('alt', ''),
                    'title': img.get('title', ''),
                    'width': img.get('width', ''),
                    'height': img.get('height', ''),
                    'loading': img.get('loading', ''),
                    'srcset': img.get('srcset', ''),
                    'sizes': img.get('sizes', ''),
                    'has_lazy_loading': bool(img.get('loading') == 'lazy')
                })
        
        return images

    def _get_robots_txt(self, url):
        """Get robots.txt content"""
        try:
            robots_url = urljoin(url, '/robots.txt')
            response = requests.get(robots_url, timeout=10)
            if response.status_code == 200:
                return {
                    'url': robots_url,
                    'content': response.text,
                    'status': response.status_code,
                    'size': len(response.text)
                }
        except Exception as e:
            logger.warning(f"Could not fetch robots.txt: {e}")
        return None

    def _get_sitemap_data(self, url):
        """Get sitemap data"""
        sitemaps = []
        
        # Try common sitemap locations
        sitemap_urls = [
            urljoin(url, '/sitemap.xml'),
            urljoin(url, '/sitemap_index.xml'),
            urljoin(url, '/sitemap.txt'),
            urljoin(url, '/sitemaps.xml')
        ]
        
        for sitemap_url in sitemap_urls:
            try:
                response = requests.get(sitemap_url, timeout=10)
                if response.status_code == 200:
                    sitemap_data = {
                        'url': sitemap_url,
                        'status': response.status_code,
                        'content_type': response.headers.get('content-type', ''),
                        'size': len(response.content)
                    }
                    
                    # Parse XML sitemaps
                    if 'xml' in sitemap_url.lower():
                        try:
                            root = ET.fromstring(response.content)
                            urls = []
                            
                            # Handle sitemap index
                            for sitemap_elem in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap'):
                                loc = sitemap_elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
                                if loc is not None:
                                    urls.append({'type': 'sitemap', 'url': loc.text})
                            
                            # Handle regular sitemap
                            for url_elem in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}url'):
                                loc = url_elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
                                lastmod = url_elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}lastmod')
                                changefreq = url_elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}changefreq')
                                priority = url_elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}priority')
                                
                                if loc is not None:
                                    url_data = {'type': 'url', 'url': loc.text}
                                    if lastmod is not None:
                                        url_data['lastmod'] = lastmod.text
                                    if changefreq is not None:
                                        url_data['changefreq'] = changefreq.text
                                    if priority is not None:
                                        url_data['priority'] = priority.text
                                    urls.append(url_data)
                            
                            sitemap_data['urls'] = urls[:100]  # Limit to first 100
                            sitemap_data['url_count'] = len(urls)
                        except ET.ParseError as e:
                            logger.warning(f"Could not parse XML sitemap {sitemap_url}: {e}")
                    
                    sitemaps.append(sitemap_data)
                    break  # Found one, don't need to check others
            except Exception as e:
                logger.warning(f"Could not fetch sitemap {sitemap_url}: {e}")
                continue
        
        return sitemaps

    def _take_screenshot(self, page):
        """Take screenshot"""
        try:
            screenshot_bytes = page.screenshot(full_page=True)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            return {
                'base64': screenshot_b64,
                'size': len(screenshot_bytes),
                'format': 'png'
            }
        except Exception as e:
            logger.error(f"Screenshot error: {str(e)}")
            return None

@app.route('/scrape', methods=['POST'])
def scrape_endpoint():
    """Main scraping endpoint"""
    try:
        data = request.get_json()
        
        if not data or 'url' not in data:
            return jsonify({'error': 'URL is required'}), 400
        
        url = data['url']
        
        # Validate URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        logger.info(f"Scraping URL: {url}")
        
        # Scrape the website
        with WebScraper() as scraper:
            result = scraper.scrape_website(url)
        
        logger.info(f"Scraping completed for: {url}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Endpoint error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/scrape/batch', methods=['POST'])
def scrape_batch_endpoint():
    """Batch scraping endpoint"""
    try:
        data = request.get_json()
        
        if not data or 'urls' not in data:
            return jsonify({'error': 'URLs list is required'}), 400
        
        urls = data['urls']
        if not isinstance(urls, list) or len(urls) == 0:
            return jsonify({'error': 'URLs must be a non-empty list'}), 400
        
        if len(urls) > 10:  # Limit batch size
            return jsonify({'error': 'Maximum 10 URLs per batch'}), 400
        
        results = []
        
        with WebScraper() as scraper:
            for url in urls:
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url
                
                logger.info(f"Scraping URL: {url}")
                result = scraper.scrape_website(url)
                results.append(result)
        
        return jsonify({'results': results, 'count': len(results)})
        
    except Exception as e:
        logger.error(f"Batch endpoint error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.route('/', methods=['GET'])
def home():
    """Home endpoint with usage info"""
    return jsonify({
        'message': 'Web Scraper API',
        'version': '2.0',
        'usage': {
            'single': 'POST to /scrape with {"url": "https://example.com"}',
            'batch': 'POST to /scrape/batch with {"urls": ["https://example1.com", "https://example2.com"]}'
        },
        'endpoints': {
            'POST /scrape': 'Scrape a single website',
            'POST /scrape/batch': 'Scrape multiple websites (max 10)',
            'GET /health': 'Health check',
            'GET /': 'This info'
        },
        'features': [
            'Complete DOM extraction (H1-H6, paragraphs, alt-tags)',
            'Meta tags & structured data (Schema.org, JSON-LD, RDFa, Microdata)',
            'Social media data (Open Graph, Twitter Cards)',
            'SEO analysis (titles, descriptions, headings)',
            'Technical data (load times, headers, security)',
            'Links analysis (internal/external)',
            'Images with all attributes',
            'Robots.txt and sitemap data',
            'Full page screenshots',
            'Mobile-friendly checks',
            'Performance metrics'
        ]
    })

if __name__ == '__main__':
    logger.info("Starting Web Scraper API...")
    app.run(host='0.0.0.0', port=8000, debug=False)
