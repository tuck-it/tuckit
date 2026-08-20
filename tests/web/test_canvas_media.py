import pytest

from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_media_renders_a_thumbnail_with_reserved_dimensions(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Canvas", spec="")
    s.draft = {"nodes": [{
        "id": "n1", "parent": None, "kind": "option", "title": "Mockup",
        "summary": "", "body": "",
        "media": [{"kind": "image", "url": "/static/web/brand/symbol.png",
                   "alt": "Wireframe", "w": 800, "h": 600}],
    }]}
    s.save(update_fields=["draft"])

    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert 'class="cnode-media"' in body
    assert 'alt="Wireframe"' in body
    # w/h are what stop the card from resizing when the image lands.
    assert 'width="800"' in body and 'height="600"' in body


@pytest.mark.django_db
def test_a_node_without_media_renders_no_media_block(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Canvas", spec="## Goal\ntext")
    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert "cnode-media" not in body


@pytest.mark.django_db
def test_media_without_dimensions_still_renders(client_local, org):
    # w/h are the anti-jump guard, not a requirement -- an agent that does not
    # know them must still be able to attach a mockup.
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="Canvas", spec="")
    s.draft = {"nodes": [{
        "id": "n1", "parent": None, "kind": "option", "title": "Mockup",
        "summary": "", "body": "",
        "media": [{"kind": "image", "url": "/static/web/brand/symbol.png"}],
    }]}
    s.save(update_fields=["draft"])

    body = client_local.get(f"/{org.slug}/slices/{s.id}/").content.decode()

    assert 'class="cnode-media"' in body
    assert "width=" not in body.split('class="cnode-media"')[1].split("</div>")[0]
