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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

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
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ]
        )
        self.context = self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            extra_http_headers={
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            }
        )
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def minify_data(self, data, level='standard'):
        """
        Minify scraped data to reduce size
        Levels: 'light', 'standard', 'aggressive'
        """
        if isinstance(data, dict) and 'error' in data:
            return data
            
        minified = data.copy()
        
        # Always clean text content
        minified = self._clean_text_content(minified)
        
        if level in ['standard', 'aggressive']:
            minified = self._remove_empty_values(minified)
            minified = self._compress_content_arrays(minified)
            
        if level == 'aggressive':
            minified = self._remove_optional_sections(minified)
            minified = self._limit_array_sizes(minified)
            
        return minified
    
    def _clean_text_content(self, data):
        """Remove excessive whitespace from text content"""
        if isinstance(data, dict):
            cleaned = {}
            for key, value in data.items():
                if isinstance(value, str):
                    # Clean excessive whitespace but preserve single spaces
                    cleaned[key] = re.sub(r'\s+', ' ', value.strip())
                else:
                    cleaned[key] = self._clean_text_content(value)
            return cleaned
        elif isinstance(data, list):
            return [self._clean_text_content(item) for item in data]
        else:
            return data
    
    def _remove_empty_values(self, data):
        """Remove empty strings, lists, and dictionaries"""
        if isinstance(data, dict):
            cleaned = {}
            for key, value in data.items():
                cleaned_value = self._remove_empty_values(value)
                # Keep non-empty values or important structural keys
                if cleaned_value or key in ['status_code', 'timestamp', 'url', 'final_url']:
                    cleaned[key] = cleaned_value
            return cleaned
        elif isinstance(data, list):
            return [self._remove_empty_values(item) for item in data if item]
        else:
            return data if data not in ['', [], {}] else None
    
    def _compress_content_arrays(self, data):
        """Compress large content arrays"""
        if isinstance(data, dict):
            compressed = {}
            for key, value in data.items():
                if key == 'content' and isinstance(value, dict):
                    # Compress content section
                    compressed_content = {}
                    for content_key, content_value in value.items():
                        if content_key == 'paragraphs' and isinstance(content_value, list):
                            # Keep only first 20 paragraphs and add summary
                            if len(content_value) > 20:
                                compressed_content[content_key] = content_value[:20]
                                compressed_content['paragraphs_total'] = len(content_value)
                            else:
                                compressed_content[content_key] = content_value
                        elif content_key == 'text_content':
                            # Truncate very long text content
                            if isinstance(content_value, str) and len(content_value) > 5000:
                                compressed_content[content_key] = content_value[:5000] + '...'
                                compressed_content['text_content_truncated'] = True
                            else:
                                compressed_content[content_key] = content_value
                        else:
                            compressed_content[content_key] = content_value
                    compressed[key] = compressed_content
                else:
                    compressed[key] = self._compress_content_arrays(value)
            return compressed
        elif isinstance(data, list):
            return [self._compress_content_arrays(item) for item in data]
        else:
            return data
    
    def _remove_optional_sections(self, data):
        """Remove optional sections for aggressive minification"""
        if not isinstance(data, dict):
            return data
            
        # Sections to remove in aggressive mode
        optional_sections = [
            'robots_txt',
            'sitemap'
        ]
        
        minified = {}
        for key, value in data.items():
            if key not in optional_sections:
                minified[key] = value
        
        # Also simplify some remaining sections
        if 'links' in minified and isinstance(minified['links'], dict):
            # Keep only counts and first few examples
            links = minified['links']
            simplified_links = {
                'internal_count': len(links.get('internal', [])),
                'external_count': len(links.get('external', [])),
                'email_count': len(links.get('email', [])),
                'phone_count': len(links.get('phone', []))
            }
            # Keep first 3 examples of each type
            for link_type in ['internal', 'external']:
                if links.get(link_type):
                    simplified_links[f'{link_type}_sample'] = links[link_type][:3]
            minified['links'] = simplified_links
            
        return minified
    
    def _limit_array_sizes(self, data):
        """Limit sizes of large arrays"""
        if isinstance(data, dict):
            limited = {}
            for key, value in data.items():
                if isinstance(value, list) and len(value) > 15:
                    # Limit arrays to 15 items and add count
                    limited[key] = value[:15]
                    limited[f'{key}_total'] = len(value)
                else:
                    limited[key] = self._limit_array_sizes(value)
            return limited
        elif isinstance(data, list):
            return [self._limit_array_sizes(item) for item in data]
        else:
            return data

    def scrape_website(self, url):
        """Enhanced website scraping with comprehensive data extraction"""
        start_time = time.time()
        
        try:
            page = self.context.new_page()
            
            # Track response for headers and performance
            response_info = {}
            navigation_start = None
            
            def handle_response(response):
                nonlocal navigation_start
                if response.url == url or response.url.rstrip('/') == url.rstrip('/'):
                    response_info['headers'] = dict(response.headers)
                    response_info['status'] = response.status
                    response_info['url'] = response.url
                    if not navigation_start:
                        navigation_start = time.time()
            
            page.on('response', handle_response)
            
            # Navigate to page with better error handling
            try:
                response = page.goto(url, wait_until='networkidle', timeout=45000)
            except Exception as e:
                # Try with domcontentloaded if networkidle fails
                logger.warning(f"NetworkIdle failed for {url}, trying domcontentloaded: {str(e)}")
                response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
            
            # Wait for additional JS rendering and lazy loading
            page.wait_for_timeout(5000)
            
            # Try to trigger lazy loading by scrolling
            try:
                page.evaluate("""
                    // Scroll to different positions to trigger lazy loading
                    const positions = [0.25, 0.5, 0.75, 1];
                    for (let i = 0; i < positions.length; i++) {
                        setTimeout(() => {
                            window.scrollTo(0, document.body.scrollHeight * positions[i]);
                        }, i * 500);
                    }
                    setTimeout(() => window.scrollTo(0, 0), 2500);
                """)
                page.wait_for_timeout(3000)
            except:
                pass
            
            # Get basic page info
            final_url = page.url
            status_code = response.status if response else None
            
            # Get page content with better encoding handling
            html_content = page.content()
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Performance metrics
            load_time = time.time() - start_time if navigation_start else None
            
            # Extract all data with comprehensive analysis
            data = {
                'url': url,
                'final_url': final_url,
                'status_code': status_code,
                'timestamp': datetime.now().isoformat(),
                'load_time_total': load_time,
                'page_info': self._extract_page_info(page, soup),
                'meta_data': self._extract_meta_data(soup),
                'structured_data': self._extract_structured_data(soup),
                'social_media': self._extract_social_media_data(soup),
                'content': self._extract_content_comprehensive(soup),
                'technical': self._extract_technical_data(page, soup, response_info),
                'seo': self._extract_seo_data(soup),
                'links': self._extract_links(soup, final_url),
                'images': self._extract_images(soup, final_url),
                'forms': self._extract_forms(soup),
                'business_info': self._extract_business_info(soup),
                'contact_info': self._extract_contact_info(soup),
                'page_structure': self._analyze_page_structure(soup),
                'robots_txt': None,
                'sitemap': None
            }
            
            # Fetch external resources in parallel (excluding screenshot)
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {
                    executor.submit(self._get_robots_txt, final_url): 'robots_txt',
                    executor.submit(self._get_sitemap_data, final_url): 'sitemap'
                }
                
                for future in as_completed(futures, timeout=30):
                    key = futures[future]
                    try:
                        data[key] = future.result()
                    except Exception as exc:
                        logger.warning(f'{key} generation failed: {exc}')
                        data[key] = None
            
            # Update SEO data with link counts
            if 'seo' in data and 'links' in data:
                data['seo']['internal_links_count'] = len(data['links'].get('internal', []))
                data['seo']['external_links_count'] = len(data['links'].get('external', []))
            
            page.close()
            return data
            
        except Exception as e:
            logger.error(f"Error scraping {url}: {str(e)}")
            return {'error': str(e), 'url': url, 'timestamp': datetime.now().isoformat()}

    def _extract_content_comprehensive(self, soup):
        """Extract comprehensive content with detailed analysis"""
        content = {
            'headings': {},
            'paragraphs': [],
            'lists': [],
            'tables': [],
            'text_content': '',
            'word_count': 0,
            'reading_time': 0,
            'text_density': 0,
            'text_blocks': [],
            'main_content': '',
            'sidebar_content': '',
            'navigation_content': '',
            'footer_content': ''
        }
        
        # Headings with hierarchy and additional info
        for i in range(1, 7):
            headings = soup.find_all(f'h{i}')
            heading_data = []
            for h in headings:
                if h.text.strip():
                    heading_data.append({
                        'text': h.text.strip(),
                        'id': h.get('id'),
                        'class': h.get('class'),
                        'level': i
                    })
            if heading_data:
                content['headings'][f'h{i}'] = heading_data
        
        # Enhanced paragraphs with context
        paragraphs = soup.find_all('p')
        for p in paragraphs:
            text = p.text.strip()
            if text and len(text) > 5:  # Filter out very short paragraphs
                para_info = {
                    'text': text,
                    'length': len(text),
                    'word_count': len(text.split()),
                    'parent_tag': p.parent.name if p.parent else None
                }
                content['paragraphs'].append(para_info)
        
        # Enhanced lists with structure
        for ul in soup.find_all(['ul', 'ol']):
            list_items = []
            for li in ul.find_all('li', recursive=False):  # Only direct children
                text = li.text.strip()
                if text:
                    list_items.append({
                        'text': text,
                        'has_links': bool(li.find('a')),
                        'nested_lists': len(li.find_all(['ul', 'ol']))
                    })
            if list_items:
                content['lists'].append({
                    'type': ul.name,
                    'items': list_items[:30],  # Limit to 30 items
                    'total_items': len(list_items),
                    'class': ul.get('class'),
                    'id': ul.get('id')
                })
        
        # Enhanced tables
        for table in soup.find_all('table'):
            table_data = {
                'headers': [],
                'rows': [],
                'caption': '',
                'summary': table.get('summary', '')
            }
            
            # Caption
            caption = table.find('caption')
            if caption:
                table_data['caption'] = caption.text.strip()
            
            # Headers from thead or first row
            thead = table.find('thead')
            if thead:
                headers = thead.find_all(['th', 'td'])
            else:
                # Try first row
                first_row = table.find('tr')
                headers = first_row.find_all('th') if first_row else []
            
            if headers:
                table_data['headers'] = [th.text.strip() for th in headers[:10]]  # Limit columns
            
            # Rows (limit to first 10 for size)
            rows = table.find_all('tr')[:10]
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if cells:
                    row_data = [cell.text.strip() for cell in cells[:10]]  # Limit columns
                    if any(row_data):  # Only include non-empty rows
                        table_data['rows'].append(row_data)
            
            if table_data['headers'] or table_data['rows']:
                content['tables'].append(table_data)
        
        # Text blocks analysis
        main_content_selectors = ['main', 'article', '.content', '.main', '#content', '#main']
        sidebar_selectors = ['aside', '.sidebar', '.side', '#sidebar']
        nav_selectors = ['nav', '.navigation', '.nav', '#navigation', '#nav']
        footer_selectors = ['footer', '.footer', '#footer']
        
        # Extract main content
        for selector in main_content_selectors:
            main_elem = soup.select_one(selector)
            if main_elem:
                content['main_content'] = main_elem.text.strip()[:2000]  # Limit length
                break
        
        # Extract sidebar content
        for selector in sidebar_selectors:
            sidebar_elem = soup.select_one(selector)
            if sidebar_elem:
                content['sidebar_content'] = sidebar_elem.text.strip()[:1000]
                break
        
        # Extract navigation content
        for selector in nav_selectors:
            nav_elem = soup.select_one(selector)
            if nav_elem:
                content['navigation_content'] = nav_elem.text.strip()[:500]
                break
        
        # Extract footer content
        for selector in footer_selectors:
            footer_elem = soup.select_one(selector)
            if footer_elem:
                content['footer_content'] = footer_elem.text.strip()[:500]
                break
        
        # Text blocks by semantic areas
        content_areas = ['header', 'main', 'article', 'section', 'aside', 'footer']
        for area in content_areas:
            elements = soup.find_all(area)
            if elements:
                area_text = []
                for elem in elements[:3]:  # Limit to first 3 of each type
                    text = elem.text.strip()
                    if text and len(text) > 20:
                        area_text.append({
                            'tag': area,
                            'text': text[:500],  # Limit length
                            'word_count': len(text.split()),
                            'id': elem.get('id'),
                            'class': elem.get('class')
                        })
                if area_text:
                    content['text_blocks'].extend(area_text)
        
        # Full text content with better cleaning
        text_soup = soup.get_text()
        content['text_content'] = re.sub(r'\s+', ' ', text_soup).strip()
        content['word_count'] = len(content['text_content'].split())
        content['reading_time'] = max(1, content['word_count'] // 200)  # 200 words per minute
        
        # Text density (ratio of text to HTML)
        html_size = len(str(soup))
        text_size = len(content['text_content'])
        content['text_density'] = round(text_size / html_size, 3) if html_size > 0 else 0
        
        return content

    def _extract_business_info(self, soup):
        """Extract business-specific information"""
        business_info = {
            'company_name': '',
            'addresses': [],
            'phone_numbers': [],
            'email_addresses': [],
            'business_hours': [],
            'social_media_profiles': [],
            'services': [],
            'products': []
        }
        
        # Company name from various sources
        title = soup.find('title')
        if title:
            business_info['company_name'] = title.text.strip()
        
        # Address patterns
        address_patterns = [
            r'\d+\s+[A-Za-z\s]+(?:street|str|avenue|ave|road|rd|drive|dr|lane|ln|boulevard|blvd).*?\d{4,5}',
            r'\d{4,5}\s+[A-Z]{2}\s+[A-Za-z\s]+',  # Dutch postal codes
            r'[A-Za-z\s]+\s+\d+[A-Za-z]?\s*,\s*\d{4,5}\s+[A-Za-z\s]+',
        ]
        
        text_content = soup.get_text()
        for pattern in address_patterns:
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            for match in matches[:3]:  # Limit to 3 addresses
                if match not in business_info['addresses']:
                    business_info['addresses'].append(match.strip())
        
        # Phone numbers (enhanced patterns)
        phone_patterns = [
            r'(\+31\s?(?:\(0\)\s?)?[1-9](?:\s?\d){8})',  # Dutch format
            r'(\+\d{1,3}\s?\d{1,14})',  # International
            r'(\b0\d{1,3}[-\s]?\d{6,7}\b)',  # Local Dutch
            r'(\b\d{3,4}[-\s]?\d{6,7}\b)'  # Local format
        ]
        
        for pattern in phone_patterns:
            matches = re.findall(pattern, text_content)
            for match in matches[:5]:  # Limit to 5 phone numbers
                clean_phone = re.sub(r'[^\d+]', '', match)
                if len(clean_phone) >= 8 and clean_phone not in business_info['phone_numbers']:
                    business_info['phone_numbers'].append(match.strip())
        
        # Email addresses
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, text_content)
        business_info['email_addresses'] = list(set(emails))[:5]  # Limit to 5 unique emails
        
        # Business hours patterns
        hours_patterns = [
            r'(?:open|hours?|tijd|tijden).*?(?:\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm))',
            r'(?:maandag|monday|ma).*?(?:vrijdag|friday|vr).*?\d{1,2}:\d{2}',
            r'\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}'
        ]
        
        for pattern in hours_patterns:
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            business_info['business_hours'].extend(matches[:3])
        
        return business_info

    def _extract_contact_info(self, soup):
        """Extract contact information comprehensively"""
        contact_info = {
            'contact_forms': [],
            'contact_pages': [],
            'social_links': [],
            'map_embeds': [],
            'contact_methods': []
        }
        
        # Contact forms
        forms = soup.find_all('form')
        for form in forms:
            form_info = {
                'action': form.get('action', ''),
                'method': form.get('method', 'get').lower(),
                'inputs': [],
                'has_email_field': False,
                'has_message_field': False
            }
            
            for inp in form.find_all(['input', 'textarea']):
                input_type = inp.get('type', 'text')
                input_name = inp.get('name', '')
                input_placeholder = inp.get('placeholder', '')
                
                form_info['inputs'].append({
                    'type': input_type,
                    'name': input_name,
                    'placeholder': input_placeholder
                })
                
                # Check for email/message fields
                if 'email' in input_name.lower() or input_type == 'email':
                    form_info['has_email_field'] = True
                if 'message' in input_name.lower() or inp.name == 'textarea':
                    form_info['has_message_field'] = True
            
            contact_info['contact_forms'].append(form_info)
        
        # Contact page links
        contact_links = soup.find_all('a', href=True)
        for link in contact_links:
            href = link.get('href', '').lower()
            text = link.text.lower().strip()
            if any(word in href or word in text for word in ['contact', 'about', 'over']):
                contact_info['contact_pages'].append({
                    'url': link.get('href'),
                    'text': link.text.strip()
                })
        
        # Social media links
        social_domains = ['facebook.com', 'twitter.com', 'linkedin.com', 'instagram.com', 
                         'youtube.com', 'tiktok.com', 'pinterest.com']
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            for domain in social_domains:
                if domain in href:
                    contact_info['social_links'].append({
                        'platform': domain.replace('.com', ''),
                        'url': href,
                        'text': link.text.strip()
                    })
                    break
        
        # Map embeds
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src', '')
            if 'maps' in src or 'embed' in src:
                contact_info['map_embeds'].append({
                    'src': src,
                    'width': iframe.get('width', ''),
                    'height': iframe.get('height', '')
                })
        
        return contact_info

    def _analyze_page_structure(self, soup):
        """Analyze the overall structure of the page"""
        structure = {
            'has_header': bool(soup.find('header')),
            'has_nav': bool(soup.find('nav')),
            'has_main': bool(soup.find('main')),
            'has_aside': bool(soup.find('aside')),
            'has_footer': bool(soup.find('footer')),
            'semantic_elements': [],
            'content_sections': 0,
            'navigation_items': 0,
            'total_elements': 0,
            'depth_analysis': {}
        }
        
        # Count semantic elements
        semantic_tags = ['header', 'nav', 'main', 'article', 'section', 'aside', 'footer']
        for tag in semantic_tags:
            elements = soup.find_all(tag)
            if elements:
                structure['semantic_elements'].append({
                    'tag': tag,
                    'count': len(elements)
                })
        
        # Count content sections
        structure['content_sections'] = len(soup.find_all(['article', 'section']))
        
        # Count navigation items
        nav_links = soup.select('nav a, .nav a, .navigation a')
        structure['navigation_items'] = len(nav_links)
        
        # Total elements
        structure['total_elements'] = len(soup.find_all())
        
        # Depth analysis
        def get_max_depth(element, current_depth=0):
            if not element.children:
                return current_depth
            return max(get_max_depth(child, current_depth + 1) 
                      for child in element.children 
                      if hasattr(child, 'children'))
        
        try:
            structure['depth_analysis']['max_nesting_depth'] = get_max_depth(soup.body) if soup.body else 0
        except:
            structure['depth_analysis']['max_nesting_depth'] = 0
        
        return structure

    # Keep existing methods for page_info, meta_data, etc. but enhance them
    def _extract_page_info(self, page, soup):
        """Extract enhanced page information"""
        title_elem = soup.find('title')
        
        # Get language from html tag or meta
        lang = soup.find('html', lang=True)
        lang = lang.get('lang') if lang else None
        if not lang:
            lang_meta = soup.find('meta', attrs={'http-equiv': 'content-language'})
            lang = lang_meta.get('content') if lang_meta else None
        
        # Get additional page info
        charset_meta = soup.find('meta', charset=True)
        charset = charset_meta.get('charset') if charset_meta else 'utf-8'
        
        return {
            'title': title_elem.text.strip() if title_elem else '',
            'title_length': len(title_elem.text.strip()) if title_elem else 0,
            'url': page.url,
            'domain': urlparse(page.url).netloc,
            'subdomain': urlparse(page.url).netloc.split('.')[0] if '.' in urlparse(page.url).netloc else '',
            'path': urlparse(page.url).path,
            'path_segments': [seg for seg in urlparse(page.url).path.split('/') if seg],
            'query': urlparse(page.url).query,
            'fragment': urlparse(page.url).fragment,
            'protocol': urlparse(page.url).scheme,
            'language': lang,
            'charset': charset,
            'is_ssl': page.url.startswith('https://'),
            'url_length': len(page.url)
        }

    def _extract_meta_data(self, soup):
        """Extract comprehensive meta data"""
        meta_data = {}
        
        # Standard meta tags
        for meta in soup.find_all('meta'):
            name = meta.get('name') or meta.get('property') or meta.get('http-equiv')
            content = meta.get('content')
            if name and content:
                # Clean content
                content = re.sub(r'\s+', ' ', content.strip())
                meta_data[name.lower()] = content
        
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
                    'href': link.get('href'),
                    'title': link.get('title', '')
                })
        if alt_langs:
            meta_data['alternate_languages'] = alt_langs
        
        # Favicon analysis
        favicon_links = []
        for link in soup.find_all('link', rel=['icon', 'shortcut icon', 'apple-touch-icon', 'apple-touch-icon-precomposed']):
            favicon_data = {
                'rel': link.get('rel'),
                'href': link.get('href'),
                'type': link.get('type', ''),
                'sizes': link.get('sizes', '')
            }
            favicon_links.append(favicon_data)
        if favicon_links:
            meta_data['favicons'] = favicon_links
        
        # CSS and JS resources (enhanced)
        stylesheets = []
        for link in soup.find_all('link', rel='stylesheet'):
            if link.get('href'):
                stylesheets.append({
                    'href': link.get('href'),
                    'media': link.get('media', 'all'),
                    'type': link.get('type', 'text/css'),
                    'is_external': link.get('href', '').startswith(('http', '//'))
                })
        if stylesheets:
            meta_data['stylesheets'] = stylesheets[:15]  # Limit to first 15
        
        # JavaScript files
        scripts = []
        for script in soup.find_all('script', src=True):
            scripts.append({
                'src': script.get('src'),
                'type': script.get('type', 'text/javascript'),
                'async': script.has_attr('async'),
                'defer': script.has_attr('defer'),
                'is_external': script.get('src', '').startswith(('http', '//'))
            })
        if scripts:
            meta_data['external_scripts'] = scripts[:15]  # Limit to first 15
        
        return meta_data

    def _extract_structured_data(self, soup):
        """Extract structured data with enhanced parsing"""
        structured_data = {
            'json_ld': [],
            'microdata': [],
            'rdfa': [],
            'schema_types': []
        }
        
        # JSON-LD with error handling and type detection
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                if script.string:
                    json_str = script.string.strip()
                    data = json.loads(json_str)
                    structured_data['json_ld'].append(data)
                    
                    # Extract schema types
                    if isinstance(data, dict) and '@type' in data:
                        structured_data['schema_types'].append(data['@type'])
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and '@type' in item:
                                structured_data['schema_types'].append(item['@type'])
            except (json.JSONDecodeError, ValueError) as e:
                logger.debug(f"Failed to parse JSON-LD: {e}")
                continue
        
        # Enhanced Microdata extraction
        for elem in soup.find_all(attrs={'itemscope': True}):
            item = self._extract_microdata_item(elem)
            if item and item.get('properties'):
                structured_data['microdata'].append(item)
                # Add to schema types if available
                if item.get('type'):
                    structured_data['schema_types'].append(item['type'])
        
        # Enhanced RDFa extraction
        for elem in soup.find_all(attrs={'typeof': True}):
            rdfa_item = {
                'typeof': elem.get('typeof'),
                'properties': {},
                'resource': elem.get('resource', ''),
                'about': elem.get('about', '')
            }
            
            # Get properties from this element and children
            for prop_elem in elem.find_all(attrs={'property': True}):
                prop = prop_elem.get('property')
                content = (prop_elem.get('content') or 
                          prop_elem.get('href') or 
                          prop_elem.text.strip())
                if content:
                    rdfa_item['properties'][prop] = content
            
            if rdfa_item['properties']:
                structured_data['rdfa'].append(rdfa_item)
                # Add to schema types
                if rdfa_item['typeof']:
                    structured_data['schema_types'].append(rdfa_item['typeof'])
        
        # Remove duplicates from schema types
        structured_data['schema_types'] = list(set(structured_data['schema_types']))
        
        return structured_data

    def _extract_microdata_item(self, elem):
        """Extract microdata item with enhanced property detection"""
        item = {
            'type': elem.get('itemtype'),
            'id': elem.get('itemid'),
            'properties': {}
        }
        
        for prop_elem in elem.find_all(attrs={'itemprop': True}):
            prop = prop_elem.get('itemprop')
            
            # Get content based on element type
            if prop_elem.name == 'meta':
                content = prop_elem.get('content')
            elif prop_elem.name in ['img', 'audio', 'video', 'source']:
                content = prop_elem.get('src')
            elif prop_elem.name == 'a':
                content = prop_elem.get('href')
            elif prop_elem.name == 'time':
                content = prop_elem.get('datetime') or prop_elem.text.strip()
            elif prop_elem.name == 'data':
                content = prop_elem.get('value') or prop_elem.text.strip()
            else:
                content = prop_elem.text.strip()
                
            if content:
                # Handle multiple values for same property
                if prop in item['properties']:
                    if not isinstance(item['properties'][prop], list):
                        item['properties'][prop] = [item['properties'][prop]]
                    item['properties'][prop].append(content)
                else:
                    item['properties'][prop] = content
            
        return item

    def _extract_social_media_data(self, soup):
        """Extract social media data with enhanced coverage"""
        social_data = {
            'open_graph': {},
            'twitter_cards': {},
            'facebook': {},
            'linkedin': {},
            'pinterest': {},
            'summary': {}
        }
        
        for meta in soup.find_all('meta'):
            property_attr = meta.get('property', '')
            name_attr = meta.get('name', '')
            content = meta.get('content', '')
            
            if not content:
                continue
            
            # Clean content
            content = re.sub(r'\s+', ' ', content.strip())
            
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
            
            # Pinterest
            elif name_attr.startswith('pinterest'):
                social_data['pinterest'][name_attr] = content
        
        # Create summary
        social_data['summary'] = {
            'has_open_graph': bool(social_data['open_graph']),
            'has_twitter_cards': bool(social_data['twitter_cards']),
            'has_facebook_meta': bool(social_data['facebook']),
            'total_social_tags': (len(social_data['open_graph']) + 
                                 len(social_data['twitter_cards']) + 
                                 len(social_data['facebook']) + 
                                 len(social_data['linkedin']) + 
                                 len(social_data['pinterest']))
        }
                
        return social_data

    def _extract_technical_data(self, page, soup, response_info):
        """Extract technical data with enhanced metrics"""
        try:
            # Performance timing
            perf_data = page.evaluate("""
                () => {
                    const timing = performance.timing;
                    const navigation = performance.navigation;
                    return {
                        loadTime: timing.loadEventEnd - timing.navigationStart,
                        domContentLoaded: timing.domContentLoadedEventEnd - timing.navigationStart,
                        firstPaint: performance.getEntriesByType('paint').find(p => p.name === 'first-paint')?.startTime || null,
                        firstContentfulPaint: performance.getEntriesByType('paint').find(p => p.name === 'first-contentful-paint')?.startTime || null,
                        navigationType: navigation.type,
                        redirectCount: navigation.redirectCount
                    };
                }
            """)
        except Exception as e:
            logger.debug(f"Performance timing failed: {e}")
            perf_data = {}
        
        return {
            'performance': perf_data,
            'html_size': len(str(soup)),
            'html_size_kb': round(len(str(soup)) / 1024, 2),
            'response_headers': response_info.get('headers', {}),
            'security': {
                'https': page.url.startswith('https://'),
                'mixed_content': self._check_mixed_content(soup, page.url),
                'hsts_header': 'strict-transport-security' in response_info.get('headers', {}),
                'csp_header': 'content-security-policy' in response_info.get('headers', {}),
                'x_frame_options': response_info.get('headers', {}).get('x-frame-options'),
                'x_content_type_options': response_info.get('headers', {}).get('x-content-type-options'),
                'referrer_policy': response_info.get('headers', {}).get('referrer-policy')
            },
            'mobile_friendly': self._check_mobile_friendly(soup),
            'accessibility': self._check_accessibility(soup),
            'page_speed_insights': self._basic_performance_metrics(soup),
            'encoding': soup.original_encoding if hasattr(soup, 'original_encoding') else 'unknown',
            'doctype': str(soup.doctype) if soup.doctype else 'html5'
        }

    def _check_mixed_content(self, soup, url):
        """Check for mixed content issues"""
        if not url.startswith('https://'):
            return []
            
        mixed_content = []
        for elem in soup.find_all(['img', 'script', 'link', 'iframe', 'audio', 'video']):
            src = elem.get('src') or elem.get('href')
            if src and src.startswith('http://'):
                mixed_content.append({
                    'element': elem.name,
                    'url': src,
                    'attribute': 'src' if elem.get('src') else 'href'
                })
        return mixed_content[:10]  # Limit to first 10

    def _check_mobile_friendly(self, soup):
        """Enhanced mobile-friendly checks"""
        viewport = soup.find('meta', attrs={'name': 'viewport'})
        
        return {
            'has_viewport': bool(viewport),
            'viewport_content': viewport.get('content') if viewport else None,
            'responsive_images': len(soup.find_all('img', srcset=True)),
            'mobile_specific_meta': bool(soup.find('meta', attrs={'name': 'format-detection'})),
            'touch_icons': len(soup.find_all('link', rel=lambda x: x and 'touch-icon' in str(x))),
            'media_queries_in_html': len(soup.find_all('style')),
            'responsive_meta_tags': len(soup.find_all('meta', attrs={'name': lambda x: x and 'mobile' in str(x).lower()}))
        }

    def _check_accessibility(self, soup):
        """Enhanced accessibility checks"""
        return {
            'images_without_alt': len(soup.find_all('img', alt=False)),
            'images_with_empty_alt': len(soup.find_all('img', alt="")),
            'images_with_alt': len(soup.find_all('img', alt=True)),
            'links_without_text': len([a for a in soup.find_all('a') if not a.text.strip() and not a.find('img')]),
            'links_with_title': len(soup.find_all('a', title=True)),
            'headings_structure': len(soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])),
            'h1_count': len(soup.find_all('h1')),
            'form_labels': len(soup.find_all('label')),
            'form_inputs': len(soup.find_all(['input', 'textarea', 'select'])),
            'lang_attribute': bool(soup.find('html', lang=True)),
            'skip_links': len(soup.find_all('a', href=lambda x: x and x.startswith('#'))),
            'aria_labels': len(soup.find_all(attrs={'aria-label': True})),
            'role_attributes': len(soup.find_all(attrs={'role': True}))
        }

    def _basic_performance_metrics(self, soup):
        """Enhanced performance metrics"""
        return {
            'images_total': len(soup.find_all('img')),
            'images_without_alt': len(soup.find_all('img', alt=False)),
            'images_with_alt': len(soup.find_all('img', alt=True)),
            'images_lazy_loading': len(soup.find_all('img', loading='lazy')),
            'images_with_srcset': len(soup.find_all('img', srcset=True)),
            'external_scripts': len([s for s in soup.find_all('script', src=True) 
                                   if s.get('src', '').startswith(('http', '//'))]),
            'inline_scripts': len([s for s in soup.find_all('script') if not s.get('src')]),
            'external_stylesheets': len([l for l in soup.find_all('link', rel='stylesheet') 
                                       if l.get('href', '').startswith(('http', '//'))]),
            'inline_styles': len(soup.find_all('style')),
            'total_links': len(soup.find_all('a', href=True)),
            'external_links': len([a for a in soup.find_all('a', href=True) 
                                 if a.get('href', '').startswith(('http', '//'))]),
            'forms': len(soup.find_all('form')),
            'iframes': len(soup.find_all('iframe')),
            'videos': len(soup.find_all('video')),
            'audios': len(soup.find_all('audio')),
            'canvas_elements': len(soup.find_all('canvas')),
            'svg_elements': len(soup.find_all('svg'))
        }

    def _extract_seo_data(self, soup):
        """Extract comprehensive SEO data"""
        title = soup.find('title')
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
        robots_meta = soup.find('meta', attrs={'name': 'robots'})
        
        seo_data = {
            'title_length': len(title.text) if title else 0,
            'title_text': title.text.strip() if title else '',
            'title_words': len(title.text.split()) if title else 0,
            'meta_description_length': len(meta_desc.get('content', '')) if meta_desc else 0,
            'meta_description_text': meta_desc.get('content', '') if meta_desc else '',
            'meta_description_words': len(meta_desc.get('content', '').split()) if meta_desc else 0,
            'meta_keywords': meta_keywords.get('content', '') if meta_keywords else '',
            'robots_meta': robots_meta.get('content', '') if robots_meta else '',
            'h1_count': len(soup.find_all('h1')),
            'h1_text': [h1.text.strip() for h1 in soup.find_all('h1')],
            'h2_count': len(soup.find_all('h2')),
            'h3_count': len(soup.find_all('h3')),
            'total_headings': len(soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])),
            'images_without_alt': len(soup.find_all('img', alt=False)),
            'images_total': len(soup.find_all('img')),
            'internal_links_count': 0,  # Will be updated after link extraction
            'external_links_count': 0,  # Will be updated after link extraction
            'canonical_url': soup.find('link', rel='canonical'),
            'schema_markup': len(soup.find_all(attrs={'itemscope': True})) > 0,
            'opengraph_present': bool(soup.find('meta', property=lambda x: x and x.startswith('og:'))),
            'twitter_cards_present': bool(soup.find('meta', attrs={'name': lambda x: x and x.startswith('twitter:')})),
            'structured_data_present': bool(soup.find('script', type='application/ld+json')),
            'word_count_estimate': len(soup.get_text().split()),
            'text_to_html_ratio': 0  # Will be calculated
        }
        
        if seo_data['canonical_url']:
            seo_data['canonical_url'] = seo_data['canonical_url'].get('href', '')
        
        # Calculate text to HTML ratio
        text_length = len(soup.get_text())
        html_length = len(str(soup))
        seo_data['text_to_html_ratio'] = round(text_length / html_length, 3) if html_length > 0 else 0
        
        return seo_data

    def _extract_links(self, soup, base_url):
        """Extract all links with enhanced categorization"""
        links = {
            'internal': [],
            'external': [],
            'all': [],
            'email': [],
            'phone': [],
            'social': [],
            'download': [],
            'navigation': [],
            'footer': []
        }
        
        base_domain = urlparse(base_url).netloc
        social_domains = ['facebook.com', 'twitter.com', 'linkedin.com', 'instagram.com', 
                         'youtube.com', 'tiktok.com', 'pinterest.com', 'snapchat.com',
                         'whatsapp.com', 'telegram.org']
        download_extensions = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', 
                              '.zip', '.rar', '.mp3', '.mp4', '.avi', '.mov', '.jpg', '.png']
        
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
                phone_clean = href[4:].replace('-', '').replace(' ', '').replace('(', '').replace(')', '')
                links['phone'].append({
                    'phone': phone_clean,
                    'original': href[4:],
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
                'nofollow': 'nofollow' in link.get('rel', []),
                'class': link.get('class', []),
                'parent_element': link.parent.name if link.parent else None
            }
            
            links['all'].append(link_data)
            
            # Categorize links
            if link_domain == base_domain or not link_domain:
                links['internal'].append(link_data)
            else:
                links['external'].append(link_data)
                
                # Check for social media
                if any(social in link_domain for social in social_domains):
                    social_link = link_data.copy()
                    social_link['platform'] = next(social.replace('.com', '') for social in social_domains if social in link_domain)
                    links['social'].append(social_link)
            
            # Check for downloads
            if any(ext in absolute_url.lower() for ext in download_extensions):
                download_link = link_data.copy()
                download_link['file_type'] = next(ext for ext in download_extensions if ext in absolute_url.lower())
                links['download'].append(download_link)
            
            # Check for navigation links
            if link.find_parent(['nav', 'header']) or 'nav' in link.get('class', []):
                links['navigation'].append(link_data)
            
            # Check for footer links
            if link.find_parent('footer') or 'footer' in link.get('class', []):
                links['footer'].append(link_data)
        
        return links

    def _extract_images(self, soup, base_url):
        """Extract all images with enhanced metadata"""
        images = []
        
        for img in soup.find_all('img'):
            src = img.get('src')
            if src:
                absolute_url = urljoin(base_url, src)
                
                # Get image format from URL
                img_format = None
                for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.avif']:
                    if ext in absolute_url.lower():
                        img_format = ext[1:]
                        break
                
                # Analyze alt text quality
                alt_text = img.get('alt', '')
                alt_quality = 'missing'
                if alt_text:
                    if len(alt_text.strip()) == 0:
                        alt_quality = 'empty'
                    elif len(alt_text) < 10:
                        alt_quality = 'short'
                    elif len(alt_text) > 100:
                        alt_quality = 'long'
                    else:
                        alt_quality = 'good'
                
                images.append({
                    'src': absolute_url,
                    'alt': alt_text,
                    'alt_quality': alt_quality,
                    'alt_length': len(alt_text),
                    'title': img.get('title', ''),
                    'width': img.get('width', ''),
                    'height': img.get('height', ''),
                    'loading': img.get('loading', ''),
                    'srcset': img.get('srcset', ''),
                    'sizes': img.get('sizes', ''),
                    'format': img_format,
                    'has_lazy_loading': bool(img.get('loading') == 'lazy'),
                    'is_responsive': bool(img.get('srcset') or img.get('sizes')),
                    'class': img.get('class', []),
                    'parent_element': img.parent.name if img.parent else None,
                    'is_decorative': not bool(alt_text) and 'decoration' in str(img.get('class')).lower()
                })
        
        return images

    def _extract_forms(self, soup):
        """Extract comprehensive form data"""
        forms = []
        
        for form in soup.find_all('form'):
            form_data = {
                'action': form.get('action', ''),
                'method': form.get('method', 'get').lower(),
                'enctype': form.get('enctype', ''),
                'name': form.get('name', ''),
                'id': form.get('id', ''),
                'class': form.get('class', []),
                'inputs': [],
                'textareas': [],
                'selects': [],
                'buttons': [],
                'field_count': 0,
                'required_fields': 0,
                'has_validation': False
            }
            
            # Extract input fields
            for inp in form.find_all('input'):
                input_data = {
                    'type': inp.get('type', 'text'),
                    'name': inp.get('name', ''),
                    'id': inp.get('id', ''),
                    'placeholder': inp.get('placeholder', ''),
                    'required': inp.has_attr('required'),
                    'pattern': inp.get('pattern', ''),
                    'min': inp.get('min', ''),
                    'max': inp.get('max', ''),
                    'maxlength': inp.get('maxlength', '')
                }
                form_data['inputs'].append(input_data)
                form_data['field_count'] += 1
                if input_data['required']:
                    form_data['required_fields'] += 1
                if input_data['pattern']:
                    form_data['has_validation'] = True
            
            # Extract textareas
            for textarea in form.find_all('textarea'):
                textarea_data = {
                    'name': textarea.get('name', ''),
                    'id': textarea.get('id', ''),
                    'placeholder': textarea.get('placeholder', ''),
                    'required': textarea.has_attr('required'),
                    'rows': textarea.get('rows', ''),
                    'cols': textarea.get('cols', ''),
                    'maxlength': textarea.get('maxlength', '')
                }
                form_data['textareas'].append(textarea_data)
                form_data['field_count'] += 1
                if textarea_data['required']:
                    form_data['required_fields'] += 1
            
            # Extract select elements
            for select in form.find_all('select'):
                options = [opt.text.strip() for opt in select.find_all('option') if opt.text.strip()]
                select_data = {
                    'name': select.get('name', ''),
                    'id': select.get('id', ''),
                    'required': select.has_attr('required'),
                    'multiple': select.has_attr('multiple'),
                    'options_count': len(options),
                    'options': options[:10]  # Limit to first 10 options
                }
                form_data['selects'].append(select_data)
                form_data['field_count'] += 1
                if select_data['required']:
                    form_data['required_fields'] += 1
            
            # Extract buttons
            for button in form.find_all(['button', 'input'], type=['submit', 'button', 'reset']):
                button_data = {
                    'type': button.get('type', 'button'),
                    'text': button.text.strip() or button.get('value', ''),
                    'name': button.get('name', ''),
                    'id': button.get('id', ''),
                    'class': button.get('class', [])
                }
                form_data['buttons'].append(button_data)
            
            forms.append(form_data)
        
        return forms

    def _get_robots_txt(self, url):
        """Get robots.txt content with timeout and error handling"""
        try:
            robots_url = urljoin(url, '/robots.txt')
            response = requests.get(robots_url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; WebScraper/1.0)'
            })
            if response.status_code == 200:
                return {
                    'url': robots_url,
                    'content': response.text[:5000],  # Limit content size
                    'status': response.status_code,
                    'size': len(response.text),
                    'last_modified': response.headers.get('last-modified', ''),
                    'content_type': response.headers.get('content-type', '')
                }
        except Exception as e:
            logger.debug(f"Could not fetch robots.txt from {url}: {e}")
        return None

    def _get_sitemap_data(self, url):
        """Get sitemap data with enhanced parsing"""
        sitemaps = []
        
        # Try common sitemap locations
        sitemap_urls = [
            urljoin(url, '/sitemap.xml'),
            urljoin(url, '/sitemap_index.xml'),
            urljoin(url, '/sitemap.txt'),
            urljoin(url, '/sitemaps.xml'),
            urljoin(url, '/wp-sitemap.xml'),
            urljoin(url, '/sitemap_index.php')
        ]
        
        for sitemap_url in sitemap_urls:
            try:
                response = requests.get(sitemap_url, timeout=20, headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; WebScraper/1.0)'
                })
                if response.status_code == 200:
                    sitemap_data = {
                        'url': sitemap_url,
                        'status': response.status_code,
                        'content_type': response.headers.get('content-type', ''),
                        'size': len(response.content),
                        'last_modified': response.headers.get('last-modified', ''),
                        'is_compressed': 'gzip' in response.headers.get('content-encoding', '')
                    }
                    
                    # Parse XML sitemaps
                    if 'xml' in sitemap_url.lower() and len(response.content) < 2000000:  # Limit size to 2MB
                        try:
                            root = ET.fromstring(response.content)
                            urls = []
                            
                            # Handle sitemap index
                            for sitemap_elem in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap'):
                                loc = sitemap_elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
                                lastmod = sitemap_elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}lastmod')
                                if loc is not None:
                                    url_data = {'type': 'sitemap', 'url': loc.text}
                                    if lastmod is not None:
                                        url_data['lastmod'] = lastmod.text
                                    urls.append(url_data)
                            
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
                            
                            sitemap_data['urls'] = urls[:500]  # Limit to first 500
                            sitemap_data['url_count'] = len(urls)
                            sitemap_data['has_images'] = bool(root.findall('.//{http://www.google.com/schemas/sitemap-image/1.1}image'))
                            sitemap_data['has_videos'] = bool(root.findall('.//{http://www.google.com/schemas/sitemap-video/1.1}video'))
                        except ET.ParseError as e:
                            logger.debug(f"Could not parse XML sitemap {sitemap_url}: {e}")
                    
                    sitemaps.append(sitemap_data)
                    break  # Found one, don't need to check others
            except Exception as e:
                logger.debug(f"Could not fetch sitemap {sitemap_url}: {e}")
                continue
        
        return sitemaps

# Flask endpoints remain the same but with better error handling
@app.route('/scrape', methods=['POST'])
def scrape_endpoint():
    """Enhanced scraping endpoint with minification support"""
    try:
        data = request.get_json()
        
        if not data or 'url' not in data:
            return jsonify({'error': 'URL is required'}), 400
        
        url = data['url']
        minify_level = data.get('minify', 'standard')  # 'light', 'standard', 'aggressive', 'none'
        
        # Validate URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        logger.info(f"Scraping URL: {url} with minify level: {minify_level}")
        
        # Scrape the website
        with WebScraper() as scraper:
            result = scraper.scrape_website(url)
            
            # Apply minification if requested
            if minify_level and minify_level != 'none':
                result = scraper.minify_data(result, minify_level)
        
        logger.info(f"Scraping completed for: {url}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Endpoint error: {str(e)}")
        return jsonify({'error': str(e), 'timestamp': datetime.now().isoformat()}), 500

@app.route('/scrape/batch', methods=['POST'])
def scrape_batch_endpoint():
    """Enhanced batch scraping endpoint with minification support"""
    try:
        data = request.get_json()
        
        if not data or 'urls' not in data:
            return jsonify({'error': 'URLs list is required'}), 400
        
        urls = data['urls']
        minify_level = data.get('minify', 'standard')
        
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
                
                # Apply minification if requested
                if minify_level and minify_level != 'none':
                    result = scraper.minify_data(result, minify_level)
                    
                results.append(result)
        
        return jsonify({'results': results, 'count': len(results), 'minify_level': minify_level})
        
    except Exception as e:
        logger.error(f"Batch endpoint error: {str(e)}")
        return jsonify({'error': str(e), 'timestamp': datetime.now().isoformat()}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy', 
        'timestamp': datetime.now().isoformat(),
        'version': '2.2'
    })

@app.route('/', methods=['GET'])
def home():
    """Enhanced home endpoint with usage info"""
    return jsonify({
        'message': 'Enhanced Web Scraper API',
        'version': '2.2',
        'usage': {
            'single': 'POST to /scrape with {"url": "https://example.com", "minify": "standard"}',
            'batch': 'POST to /scrape/batch with {"urls": ["https://example1.com"], "minify": "aggressive"}'
        },
        'minify_levels': {
            'none': 'No minification (full data)',
            'light': 'Basic text cleaning only',
            'standard': 'Remove empty values and compress content (recommended)',
            'aggressive': 'Maximum compression, remove optional sections'
        },
        'endpoints': {
            'POST /scrape': 'Scrape a single website',
            'POST /scrape/batch': 'Scrape multiple websites (max 10)',
            'GET /health': 'Health check',
            'GET /': 'This info'
        },
        'features': [
            'Comprehensive content extraction with semantic analysis',
            'Enhanced meta tags & structured data parsing',
            'Business information extraction (addresses, phones, emails)',
            'Contact information detection',
            'Page structure analysis',
            'Comprehensive SEO analysis',
            'Advanced technical performance metrics',
            'Enhanced security and accessibility checks',
            'Detailed links analysis with categorization',
            'Advanced image analysis with quality assessment',
            'Comprehensive form extraction and analysis',
            'Enhanced robots.txt and sitemap analysis',
            'NO screenshots (removed for efficiency)',
            'Advanced data minification for API efficiency',
            'Enhanced mobile-friendly and accessibility checks',
            'Business hours and service extraction',
            'Social media profile detection'
        ]
    })

if __name__ == '__main__':
    logger.info("Starting Enhanced Web Scraper API v2.2...")
    app.run(host='0.0.0.0', port=10000, debug=False)
