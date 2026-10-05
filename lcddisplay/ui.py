import tkinter as tk

root = tk.Tk()
root.attributes("-fullscreen", True)

label = tk.Label(
    root,
    text="MODUS Golf",
    font=("Arial", 40),
    fg="white",
    bg="black"
)

label.pack(expand=True)

root.mainloop()