from services.youtube import youtube_monitor
from models.monitored_source import PlatformType

SAMPLE_ATOM_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
  <link rel="hub" href="https://pubsubhubbub.appspot.com"/>
  <title>Channel Uploads</title>
  <updated>2026-11-08T10:00:00+00:00</updated>
  <entry>
    <id>yt:video:abc123xyz78</id>
    <yt:videoId>abc123xyz78</yt:videoId>
    <yt:channelId>UCBJycsmduvYEL83R_U4JriQ</yt:channelId>
    <title>M3 MacBook Pro Review: The Complete Breakdown!</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=abc123xyz78"/>
    <author>
      <name>Marques Brownlee</name>
      <uri>https://www.youtube.com/channel/UCBJycsmduvYEL83R_U4JriQ</uri>
    </author>
    <published>2026-11-08T09:30:00+00:00</published>
    <updated>2026-11-08T09:30:00+00:00</updated>
  </entry>
</feed>
"""


def test_parse_youtube_atom_feed():
    posts = youtube_monitor.parse_atom_feed(SAMPLE_ATOM_FEED)
    assert len(posts) == 1
    post = posts[0]

    assert post.platform == PlatformType.YOUTUBE
    assert post.post_id == "abc123xyz78"
    assert post.creator_name == "Marques Brownlee"
    assert post.creator_handle == "@Marques Brownlee"
    assert post.post_url == "https://www.youtube.com/watch?v=abc123xyz78"
    assert "M3 MacBook Pro Review" in post.caption
    assert post.preview_image_url == "https://i.ytimg.com/vi/abc123xyz78/hqdefault.jpg"

