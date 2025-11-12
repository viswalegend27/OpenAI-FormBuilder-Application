document.addEventListener("DOMContentLoaded", async () => {
    const statusElement = document.getElementById("status");
    const responsesContainer = document.getElementById("responses");

    try {
        statusElement.textContent = "Loading recent responses...";
        const response = await fetch("/api/responses");
        if (!response.ok) throw new Error("Failed to fetch responses");

        const data = await response.json();
        if (data.length === 0) {
            responsesContainer.innerHTML = "<p>No recent responses found.</p>";
        } else {
            data.forEach(response => {
                const responseElement = document.createElement("div");
                responseElement.className = "response-item";
                responseElement.innerHTML = `
                    <h3>User: ${response.user}</h3>
                    <p>Response: ${response.content}</p>
                    <p>Timestamp: ${new Date(response.timestamp).toLocaleString()}</p>
                `;
                responsesContainer.appendChild(responseElement);
            });
        }
    } catch (error) {
        console.error("Error loading responses:", error);
        statusElement.textContent = "Error loading responses.";
    }
});