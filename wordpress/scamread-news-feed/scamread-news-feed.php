<?php
/**
 * Plugin Name:       ScamRead News Feed
 * Plugin URI:        https://github.com/bayardkalyan/scamread-cyber-newx-api
 * Description:       Shows the ScamRead cyber news feed: AI-written headlines and summaries with links to the original articles. Use the shortcode [scamread_news].
 * Version:           1.0.1
 * Requires at least: 5.8
 * Requires PHP:      7.4
 * Author:            ScamRead
 * License:           MIT
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'SRN_VERSION', '1.0.1' );
define( 'SRN_DEFAULT_BASE', 'https://bayardkalyan.github.io/scamread-cyber-newx-api/' );
define( 'SRN_CACHE_SECONDS', 5 * MINUTE_IN_SECONDS );

/* ------------------------------------------------------------------ */
/* Settings: Settings -> ScamRead News                                 */
/* ------------------------------------------------------------------ */

function srn_base_url() {
	$url = get_option( 'srn_base_url', SRN_DEFAULT_BASE );
	return trailingslashit( $url ? $url : SRN_DEFAULT_BASE );
}

add_action( 'admin_init', function () {
	register_setting( 'srn_settings', 'srn_base_url', array(
		'type'              => 'string',
		'sanitize_callback' => function ( $value ) {
			delete_transient( 'srn_feed' );
			delete_transient( 'srn_top' );
			$value = esc_url_raw( trim( (string) $value ), array( 'https', 'http' ) );
			return $value ? trailingslashit( $value ) : SRN_DEFAULT_BASE;
		},
		'default'           => SRN_DEFAULT_BASE,
	) );
} );

add_action( 'admin_menu', function () {
	add_options_page( 'ScamRead News', 'ScamRead News', 'manage_options', 'scamread-news', 'srn_settings_page' );
} );

function srn_settings_page() {
	if ( ! current_user_can( 'manage_options' ) ) {
		return;
	}
	$feed = srn_get_data( 'feed' );
	?>
	<div class="wrap">
		<h1>ScamRead News Feed</h1>
		<form method="post" action="options.php">
			<?php settings_fields( 'srn_settings' ); ?>
			<table class="form-table" role="presentation">
				<tr>
					<th scope="row"><label for="srn_base_url">Feed folder URL</label></th>
					<td>
						<input name="srn_base_url" id="srn_base_url" type="url" class="regular-text code"
							value="<?php echo esc_attr( srn_base_url() ); ?>">
						<p class="description">The folder that holds feed.json and top.json.</p>
					</td>
				</tr>
			</table>
			<?php submit_button(); ?>
		</form>
		<h2>Status</h2>
		<?php if ( $feed ) : ?>
			<p>Feed is working: <?php echo esc_html( count( $feed['items'] ) ); ?> stories, last updated
				<?php echo esc_html( srn_time_ago( isset( $feed['updated_at'] ) ? $feed['updated_at'] : '' ) ); ?>.</p>
		<?php else : ?>
			<p><strong>Could not load the feed.</strong> Check the URL above.</p>
		<?php endif; ?>
		<h2>How to use</h2>
		<p>Add a Shortcode block to any page or post:</p>
		<p><code>[scamread_news]</code> latest stories (20 by default)</p>
		<p><code>[scamread_news view="top" limit="5" title="Today's top 5"]</code> most important stories of the last 24 hours</p>
		<p><code>[scamread_news category="scam-phishing" limit="10"]</code> one category only. Categories:
			<?php echo esc_html( implode( ', ', array_keys( srn_category_labels() ) ) ); ?></p>
		<p><code>refresh="300"</code> sets how often (in seconds) the list updates itself while a visitor has the page open. Use <code>refresh="0"</code> to turn it off.</p>
	</div>
	<?php
}

/* ------------------------------------------------------------------ */
/* Data: fetch JSON server-side, cache it, keep a last-good copy       */
/* ------------------------------------------------------------------ */

function srn_get_data( $view ) {
	$view = ( 'top' === $view ) ? 'top' : 'feed';
	$key  = 'srn_' . $view;

	$cached = get_transient( $key );
	if ( is_array( $cached ) ) {
		return $cached;
	}

	$response = wp_remote_get( srn_base_url() . $view . '.json', array(
		'timeout' => 8,
		'headers' => array( 'Accept' => 'application/json' ),
	) );

	if ( ! is_wp_error( $response ) && 200 === (int) wp_remote_retrieve_response_code( $response ) ) {
		$data = json_decode( wp_remote_retrieve_body( $response ), true );
		if ( is_array( $data ) && isset( $data['items'] ) && is_array( $data['items'] ) ) {
			set_transient( $key, $data, SRN_CACHE_SECONDS );
			update_option( $key . '_last_good', $data, false );
			return $data;
		}
	}

	// Source is down: serve the last copy that worked, and retry in a minute.
	$last = get_option( $key . '_last_good' );
	if ( is_array( $last ) ) {
		set_transient( $key, $last, MINUTE_IN_SECONDS );
		return $last;
	}
	return null;
}

/* Visitors' browsers poll this WordPress URL, so the feed's real address stays private. */
add_action( 'rest_api_init', function () {
	register_rest_route( 'scamread-news/v1', '/(?P<view>feed|top)', array(
		'methods'             => 'GET',
		'permission_callback' => '__return_true',
		'callback'            => function ( $request ) {
			$data = srn_get_data( $request['view'] );
			if ( ! $data ) {
				return new WP_Error( 'srn_unavailable', 'News feed unavailable', array( 'status' => 503 ) );
			}
			$items = array();
			foreach ( $data['items'] as $item ) {
				$clean = srn_clean_item( $item );
				if ( $clean ) {
					$items[] = $clean;
				}
			}
			$response = rest_ensure_response( array(
				'updated_at' => isset( $data['updated_at'] ) ? (string) $data['updated_at'] : '',
				'items'      => $items,
			) );
			// Page caches (LiteSpeed and others) must not keep this: it is the live-update source.
			$response->header( 'Cache-Control', 'no-cache, max-age=0' );
			$response->header( 'X-LiteSpeed-Cache-Control', 'no-cache' );
			return $response;
		},
	) );
} );

/* ------------------------------------------------------------------ */
/* Rendering                                                           */
/* ------------------------------------------------------------------ */

function srn_category_labels() {
	return array(
		'data-breach'    => 'Data breach',
		'scam-phishing'  => 'Scam & phishing',
		'vulnerability'  => 'Vulnerability',
		'ransomware'     => 'Ransomware',
		'malware'        => 'Malware',
		'ai-security'    => 'AI security',
		'privacy-policy' => 'Privacy & policy',
		'other'          => 'Cyber news',
	);
}

function srn_time_ago( $iso ) {
	$ts = strtotime( (string) $iso );
	if ( ! $ts ) {
		return '';
	}
	return sprintf( '%s ago', human_time_diff( $ts, time() ) );
}

/* Keep only the fields we render, with only http(s) links. */
function srn_clean_item( $item ) {
	if ( ! is_array( $item ) || empty( $item['headline'] ) ) {
		return null;
	}
	$labels   = srn_category_labels();
	$category = isset( $item['category'] ) && isset( $labels[ $item['category'] ] ) ? $item['category'] : 'other';
	$sources  = array();
	if ( ! empty( $item['sources'] ) && is_array( $item['sources'] ) ) {
		foreach ( $item['sources'] as $source ) {
			$url = isset( $source['url'] ) ? esc_url_raw( $source['url'], array( 'http', 'https' ) ) : '';
			if ( $url ) {
				$sources[] = array(
					'name' => isset( $source['name'] ) ? wp_strip_all_tags( (string) $source['name'] ) : wp_parse_url( $url, PHP_URL_HOST ),
					'url'  => $url,
				);
			}
		}
	}
	if ( ! $sources ) {
		return null;
	}
	return array(
		'id'        => isset( $item['id'] ) ? sanitize_key( $item['id'] ) : '',
		'headline'  => wp_strip_all_tags( (string) $item['headline'] ),
		'summary'   => isset( $item['summary'] ) ? wp_strip_all_tags( (string) $item['summary'] ) : '',
		'category'  => $category,
		'label'     => $labels[ $category ],
		'published' => isset( $item['published'] ) ? (string) $item['published'] : '',
		'sources'   => $sources,
	);
}

function srn_render_item( $item ) {
	ob_start();
	?>
	<article class="srn-item">
		<div class="srn-meta">
			<span class="srn-cat srn-cat-<?php echo esc_attr( $item['category'] ); ?>"><?php echo esc_html( $item['label'] ); ?></span>
			<?php if ( $item['published'] ) : ?>
				<time datetime="<?php echo esc_attr( $item['published'] ); ?>"><?php echo esc_html( srn_time_ago( $item['published'] ) ); ?></time>
			<?php endif; ?>
		</div>
		<h3 class="srn-headline"><?php echo esc_html( $item['headline'] ); ?></h3>
		<?php if ( $item['summary'] ) : ?>
			<p class="srn-summary"><?php echo esc_html( $item['summary'] ); ?></p>
		<?php endif; ?>
		<p class="srn-links">
			<?php if ( 1 === count( $item['sources'] ) ) : ?>
				<a href="<?php echo esc_url( $item['sources'][0]['url'] ); ?>" target="_blank" rel="noopener nofollow">Read full article on <?php echo esc_html( $item['sources'][0]['name'] ); ?> &rarr;</a>
			<?php else : ?>
				Read full article:
				<?php
				$links = array();
				foreach ( $item['sources'] as $source ) {
					$links[] = sprintf( '<a href="%s" target="_blank" rel="noopener nofollow">%s</a>', esc_url( $source['url'] ), esc_html( $source['name'] ) );
				}
				echo implode( ' &middot; ', $links ); // phpcs:ignore WordPress.Security.EscapeOutput -- escaped above
				?>
			<?php endif; ?>
		</p>
	</article>
	<?php
	return ob_get_clean();
}

function srn_shortcode( $atts ) {
	$a = shortcode_atts( array(
		'view'     => 'feed',
		'limit'    => 20,
		'category' => '',
		'refresh'  => 300,
		'title'    => '',
	), $atts, 'scamread_news' );

	$view     = ( 'top' === $a['view'] ) ? 'top' : 'feed';
	$limit    = max( 1, min( 60, (int) $a['limit'] ) );
	$category = sanitize_key( $a['category'] );
	$refresh  = max( 0, (int) $a['refresh'] );
	if ( $refresh > 0 && $refresh < 60 ) {
		$refresh = 60;
	}

	// Keep cached copies of pages with the feed short-lived (LiteSpeed Cache; ignored if not installed).
	do_action( 'litespeed_control_set_ttl', 300 );

	wp_enqueue_style( 'srn-style', plugins_url( 'assets/scamread-news.css', __FILE__ ), array(), SRN_VERSION );
	if ( $refresh > 0 ) {
		wp_enqueue_script( 'srn-script', plugins_url( 'assets/scamread-news.js', __FILE__ ), array(), SRN_VERSION, true );
	}

	$data  = srn_get_data( $view );
	$items = array();
	if ( $data ) {
		foreach ( $data['items'] as $raw ) {
			$item = srn_clean_item( $raw );
			if ( $item && ( ! $category || $item['category'] === $category ) ) {
				$items[] = $item;
			}
			if ( count( $items ) >= $limit ) {
				break;
			}
		}
	}

	ob_start();
	?>
	<section class="srn-feed"
		data-endpoint="<?php echo esc_url( rest_url( 'scamread-news/v1/' . $view ) ); ?>"
		data-limit="<?php echo esc_attr( $limit ); ?>"
		data-category="<?php echo esc_attr( $category ); ?>"
		data-refresh="<?php echo esc_attr( $refresh ); ?>">
		<?php if ( $a['title'] ) : ?>
			<h2 class="srn-title"><?php echo esc_html( $a['title'] ); ?></h2>
		<?php endif; ?>
		<div class="srn-list">
			<?php
			if ( $items ) {
				foreach ( $items as $item ) {
					echo srn_render_item( $item ); // phpcs:ignore WordPress.Security.EscapeOutput -- escaped in srn_render_item
				}
			} else {
				echo '<p class="srn-empty">No news to show right now. Please check back soon.</p>';
			}
			?>
		</div>
		<p class="srn-footer">Summaries are written by AI from the original reports.
			<?php if ( $data && ! empty( $data['updated_at'] ) ) : ?>
				Updated <span class="srn-updated"><?php echo esc_html( srn_time_ago( $data['updated_at'] ) ); ?></span>.
			<?php endif; ?>
		</p>
	</section>
	<?php
	return ob_get_clean();
}
add_shortcode( 'scamread_news', 'srn_shortcode' );
