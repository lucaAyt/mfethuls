if __name__ == "__main__":
    import uvicorn

    uvicorn.run("mfethuls.quack_server:app", host="0.0.0.0", port=8500, reload=True)
