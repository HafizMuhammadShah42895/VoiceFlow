from PIL import Image, ImageDraw

def create_glass_icon():
    size = 256
    img = Image.new('RGBA', (size, size), (0,0,0,0))
    draw = ImageDraw.Draw(img)

    radius = 50
    x0, y0 = 16, 16
    x1, y1 = size - 16, size - 16
    fill = (20, 20, 33, 220)  # Dark frosted glass
    outline = (255, 255, 255, 120) # Bright frosty border
    width = 3

    # Draw rounded rectangle
    draw.pieslice([x0, y0, x0+radius*2, y0+radius*2], 180, 270, fill=fill)
    draw.pieslice([x1-radius*2, y0, x1, y0+radius*2], 270, 360, fill=fill)
    draw.pieslice([x0, y1-radius*2, x0+radius*2, y1], 90, 180, fill=fill)
    draw.pieslice([x1-radius*2, y1-radius*2, x1, y1], 0, 90, fill=fill)
    draw.rectangle([x0+radius, y0, x1-radius, y1], fill=fill)
    draw.rectangle([x0, y0+radius, x1, y1-radius], fill=fill)

    # Draw border
    draw.arc([x0, y0, x0+radius*2, y0+radius*2], 180, 270, fill=outline, width=width)
    draw.arc([x1-radius*2, y0, x1, y0+radius*2], 270, 360, fill=outline, width=width)
    draw.arc([x0, y1-radius*2, x0+radius*2, y1], 90, 180, fill=outline, width=width)
    draw.arc([x1-radius*2, y1-radius*2, x1, y1], 0, 90, fill=outline, width=width)
    draw.line([x0+radius, y0, x1-radius, y0], fill=outline, width=width)
    draw.line([x0+radius, y1, x1-radius, y1], fill=outline, width=width)
    draw.line([x0, y0+radius, x0, y1-radius], fill=outline, width=width)
    draw.line([x1, y0+radius, x1, y1-radius], fill=outline, width=width)

    # Load logo
    logo = Image.open('static/img/logo_final.png').convert("RGBA")
    
    # Resize logo
    max_logo_size = 180
    lw, lh = logo.size
    ratio = min(max_logo_size/lw, max_logo_size/lh)
    new_lw, new_lh = int(lw*ratio), int(lh*ratio)
    logo = logo.resize((new_lw, new_lh), Image.Resampling.LANCZOS)

    # Paste
    paste_x = (size - new_lw) // 2
    paste_y = (size - new_lh) // 2
    img.paste(logo, (paste_x, paste_y), logo)

    img.save('app.ico', format='ICO', sizes=[(256, 256)])

if __name__ == '__main__':
    create_glass_icon()
