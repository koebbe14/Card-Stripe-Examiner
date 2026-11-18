from PIL import Image, ImageDraw, ImageFilter
S = 1024

def rounded(draw, box, r, fill, outline=None, width=0):
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
# Background tile: navy with a subtle lighter top.
rounded(d, (24, 24, S - 24, S - 24), 200, (27, 40, 56, 255))
grad = Image.new("RGBA", (S, S), (0, 0, 0, 0))
gp = grad.load()
for y in range(S):
    t = max(0.0, 1 - y / (S * 0.75))
    for x in range(S):
        gp[x, y] = (70, 100, 135, int(110 * t * t))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((24, 24, S - 24, S - 24), radius=200, fill=255)
img.paste(Image.alpha_composite(img, grad), (0, 0), mask)

# Card (drawn flat, then rotated a little).
card = Image.new("RGBA", (S, S), (0, 0, 0, 0))
cd = ImageDraw.Draw(card)
cx0, cy0, cx1, cy1 = 150, 250, 840, 690
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle((cx0 + 16, cy0 + 26, cx1 + 16, cy1 + 26), radius=54, fill=(0, 0, 0, 140))
shadow = shadow.filter(ImageFilter.GaussianBlur(22))
card = Image.alpha_composite(card, shadow)
cd = ImageDraw.Draw(card)
rounded(cd, (cx0, cy0, cx1, cy1), 54, (241, 245, 249, 255))
# magnetic stripe
cd.rectangle((cx0, cy0 + 70, cx1, cy0 + 170), fill=(15, 23, 42, 255))
# printed details: chip-free lines for name/number
for i, w in enumerate((330, 230)):
    y = cy0 + 260 + i * 70
    rounded(cd, (cx0 + 60, y, cx0 + 60 + w, y + 34), 17, (148, 163, 184, 255))
card = card.rotate(-8, resample=Image.BICUBIC, center=(S / 2, S / 2))
img = Image.alpha_composite(img, card)

# Magnifying glass over the stripe.
g = Image.new("RGBA", (S, S), (0, 0, 0, 0))
gd = ImageDraw.Draw(g)
ccx, ccy, r = 610, 470, 175
# handle
gd.line((ccx + 120, ccy + 120, ccx + 290, ccy + 290), fill=(20, 184, 166, 255), width=78)
gd.ellipse((ccx + 290 - 39, ccy + 290 - 39, ccx + 290 + 39, ccy + 290 + 39), fill=(20, 184, 166, 255))
# lens glass (light tint) and ring
gd.ellipse((ccx - r, ccy - r, ccx + r, ccy + r), fill=(204, 251, 241, 110))
gd.ellipse((ccx - r, ccy - r, ccx + r, ccy + r), outline=(20, 184, 166, 255), width=46)
# highlight
gd.arc((ccx - r + 55, ccy - r + 55, ccx + r - 55, ccy + r - 55), start=200, end=255, fill=(255, 255, 255, 200), width=20)
img = Image.alpha_composite(img, g)

img.save("icon-1024.png")
sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
img.save("app.ico", sizes=[(s, s) for s in sizes])
img.resize((256, 256), Image.LANCZOS).save("icon-256.png")
# preview sheet
sheet = Image.new("RGBA", (256 + 128 + 64 + 48 + 32 + 16 + 80, 270), (244, 246, 248, 255))
x = 10
for s in (256, 128, 64, 48, 32, 16):
    sheet.alpha_composite(img.resize((s, s), Image.LANCZOS), (x, 260 - s))
    x += s + 10
sheet.save("preview.png")
print("ok")
