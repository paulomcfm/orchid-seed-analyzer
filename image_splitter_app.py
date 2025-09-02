import os
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

class ImageSplitterApp:
    # Original rectangle and sub-rectangle sizes (in original image pixels)
    RECT_ORIG_W = 5676
    RECT_ORIG_H = 1892
    SUB_ORIG_W = 946
    SUB_ORIG_H = 946

    def __init__(self, root):
        self.root = root
        self.root.title("Image Splitter")

        # Toolbar with buttons
        toolbar = tk.Frame(root)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        open_btn = tk.Button(toolbar, text="Open Image", command=self.open_image)
        open_btn.pack(side=tk.LEFT, padx=5, pady=5)

        split_btn = tk.Button(toolbar, text="Split & Save", command=self.split_and_save)
        split_btn.pack(side=tk.LEFT, padx=5, pady=5)

        # Canvas for image display
        self.canvas = tk.Canvas(root, cursor="cross")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Bindings for rectangle dragging
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)

        self.img = None
        self.photo = None
        self.rect = None
        self.file_path = None
        self.start_x = self.start_y = None
        self.scale = 1.0

    def open_image(self):
        file_path = filedialog.askopenfilename(
            title="Select Image",
            filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.bmp;*.gif")]
        )
        if not file_path:
            return
        self.file_path = file_path
        # Load full-resolution image
        try:
            self.img = Image.open(file_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open image:\n{e}")
            return

        img_w, img_h = self.img.size

        # Compute scale to fit screen (without altering original)
        # Add some padding to avoid taking the full screen
        pad_x = 100
        pad_y = 150 # More padding for toolbar etc.
        screen_w = self.root.winfo_screenwidth() - pad_x
        screen_h = self.root.winfo_screenheight() - pad_y
        self.scale = min(screen_w / img_w, screen_h / img_h, 1.0) # Ensure scale is not > 1

        # Create a downscaled preview for display
        disp_w = int(img_w * self.scale)
        disp_h = int(img_h * self.scale)
        # Use ANTIALIAS for better quality resizing
        disp_img = self.img.resize((disp_w, disp_h), Image.Resampling.LANCZOS) # Updated PIL resampling
        self.photo = ImageTk.PhotoImage(disp_img)

        # Configure canvas
        self.canvas.config(width=disp_w, height=disp_h)
        self.canvas.delete("all") # Clear previous image/rect
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

        # Draw draggable rectangle in display coords
        rect_disp_w = int(self.RECT_ORIG_W * self.scale)
        rect_disp_h = int(self.RECT_ORIG_H * self.scale)

        # Ensure rectangle doesn't start bigger than the display image
        rect_disp_w = min(rect_disp_w, disp_w)
        rect_disp_h = min(rect_disp_h, disp_h)

        # Initial position (top-left corner)
        initial_x1 = 0
        initial_y1 = 0

        self.rect = self.canvas.create_rectangle(
            initial_x1, initial_y1,
            initial_x1 + rect_disp_w, initial_y1 + rect_disp_h,
            outline='red', width=2, tags="selection_rect"
        )
        # Clear any previous status text
        self.canvas.delete("status_text")


    def on_press(self, event):
        if not self.rect:
            return
        # Check if the click is inside the rectangle
        x1, y1, x2, y2 = self.canvas.coords(self.rect)
        if x1 <= event.x <= x2 and y1 <= event.y <= y2:
            # Store the starting position of the mouse relative to the canvas
            self.start_x = event.x
            self.start_y = event.y
        else:
            # Click was outside the rectangle, ignore drag
            self.start_x = None
            self.start_y = None

    def on_drag(self, event):
        if self.start_x is None or self.start_y is None or not self.rect:
            # Only drag if the press started inside the rectangle
            return

        # Calculate the distance moved
        dx = event.x - self.start_x
        dy = event.y - self.start_y

        # Get current rectangle coordinates and dimensions (display scale)
        x1, y1, x2, y2 = self.canvas.coords(self.rect)
        rect_disp_w = x2 - x1
        rect_disp_h = y2 - y1

        # Calculate potential new top-left corner
        new_x1 = x1 + dx
        new_y1 = y1 + dy

        # Get canvas (display image) dimensions for boundary check
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()

        # Clamp the new position to stay within the canvas boundaries
        final_x1 = max(0, min(new_x1, canvas_w - rect_disp_w))
        final_y1 = max(0, min(new_y1, canvas_h - rect_disp_h))

        # Move the rectangle
        self.canvas.coords(self.rect,
                           final_x1, final_y1,
                           final_x1 + rect_disp_w, final_y1 + rect_disp_h)

        # Update the starting position for the next drag event
        self.start_x = event.x
        self.start_y = event.y

    def split_and_save(self):
        if not self.img or not self.rect:
            messagebox.showwarning("No Image", "Please load an image first.")
            return
        if not self.file_path:
             messagebox.showerror("Error", "Cannot save, original file path not found.")
             return

        base, ext = os.path.splitext(os.path.basename(self.file_path))
        folder = os.path.dirname(self.file_path)

        # Get rectangle coordinates in display scale
        x1_disp, y1_disp, x2_disp, y2_disp = self.canvas.coords(self.rect)

        # Convert display coordinates back to original image coordinates
        # Ensure division by scale is done carefully, handling potential float inaccuracies
        orig_x1 = int(x1_disp / self.scale)
        orig_y1 = int(y1_disp / self.scale)
        # Use the predefined original rectangle dimensions for consistency
        # The actual width/height might be slightly off due to scaling/clamping
        orig_rect_w = self.RECT_ORIG_W
        orig_rect_h = self.RECT_ORIG_H

        # Ensure the crop area doesn't exceed the original image bounds
        img_w, img_h = self.img.size
        if orig_x1 + orig_rect_w > img_w:
            orig_rect_w = img_w - orig_x1
        if orig_y1 + orig_rect_h > img_h:
            orig_rect_h = img_h - orig_y1
        if orig_x1 < 0: orig_x1 = 0 # Should not happen with clamping, but safety check
        if orig_y1 < 0: orig_y1 = 0

        index = 1
        num_saved = 0
        try:
            # Iterate based on the *original* sub-rectangle dimensions within the selected *original* rectangle area
            for row_offset in range(0, orig_rect_h, self.SUB_ORIG_H):
                for col_offset in range(0, orig_rect_w, self.SUB_ORIG_W):
                    # Define the crop box relative to the original image's top-left (0,0)
                    crop_left = orig_x1 + col_offset
                    crop_top = orig_y1 + row_offset
                    # Calculate the right and bottom edges, ensuring they don't exceed the selected rect bounds
                    crop_right = min(orig_x1 + col_offset + self.SUB_ORIG_W, orig_x1 + orig_rect_w)
                    crop_bottom = min(orig_y1 + row_offset + self.SUB_ORIG_H, orig_y1 + orig_rect_h)

                    # Check if the calculated crop box has valid dimensions (width/height > 0)
                    if crop_right > crop_left and crop_bottom > crop_top:
                        crop_box = (crop_left, crop_top, crop_right, crop_bottom)
                        region = self.img.crop(crop_box)

                        # Construct save path
                        save_path = os.path.join(folder, f"{base}_{index}{ext}")
                        region.save(save_path)
                        # print(f"Saved: {save_path} from box {crop_box}") # Optional: for debugging
                        index += 1
                        num_saved += 1
                    # else: # Optional: Debugging for invalid crop boxes
                        # print(f"Skipped invalid crop box: L{crop_left}, T{crop_top}, R{crop_right}, B{crop_bottom}")


            messagebox.showinfo("Success", f"{num_saved} sub-images saved successfully in '{folder}'.")

            # Optionally ask before deleting original
            if messagebox.askyesno("Delete Original?", f"Do you want to delete the original file?\n{self.file_path}"):
                 try:
                     os.remove(self.file_path)
                     print(f"Original file '{self.file_path}' deleted.")
                     # Clear the display after deleting
                     self.canvas.delete("all")
                     self.img = None
                     self.photo = None
                     self.rect = None
                     self.file_path = None
                     self.root.title("Image Splitter") # Reset title
                 except OSError as e:
                     messagebox.showerror("Deletion Error", f"Could not delete original file:\n{e}")
                 except Exception as e: # Catch other potential errors
                      messagebox.showerror("Error", f"An unexpected error occurred during deletion:\n{e}")

            else:
                 # Overlay success text on canvas if original not deleted
                self.canvas.delete("status_text") # Remove previous text if any
                self.canvas.create_text(
                    self.canvas.winfo_width() // 2, 20, # Centered horizontally, near top
                    text="Split complete!",
                    fill="green",
                    font=("Helvetica", 16, "bold"),
                    tags="status_text",
                    anchor=tk.N # Anchor text at the top-center
                )

        except Exception as e:
            messagebox.showerror("Save Error", f"An error occurred while splitting or saving:\n{e}")


if __name__ == '__main__':
    root = tk.Tk()
    app = ImageSplitterApp(root)
    root.mainloop()