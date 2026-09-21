# LinkedIn post: lane 3 (attach chart_models.png)

I had a model read 5,000 customer reviews and answer 9 questions about each one. It took 69 seconds and cost 15 cents.

Scaled up, that is $29 per million reviews.

Most businesses are sitting on a pile of text nobody has read: reviews, support tickets, call notes, dead CRM records. The reason is cost. Putting every row through a big LLM is thousands of dollars, so people sample 200 rows and guess.

I ran the same job four ways on public Yelp reviews. One call per review, nine questions each: star rating, sentiment, and seven yes/no tags (mentions staff, price, wait time, cleanliness, wants compensation, will come back, health or safety problem).

Cost per 1 million reviews:
Jev 1.13: $29
GPT-5.6 Luna: $189
Gemini 3.8 Flash: $475
GPT-6 Astra: $6,174

Quality, checked against the real star ratings:
Predicted stars within 1 of the real rating: Jev 98.3%, Luna 97.7%, Gemini 96.0%, Astra 100%
On the seven tags, Jev agreed with GPT-6 Astra 97% of the time.

Jev is TypeSafe's new decision model. It does not write text, it answers typed questions, and it reads the review once no matter how many questions you ask. That is why nine questions cost about the same as one.

From my laptop it ran 72 reviews per second. A million rows is an afternoon.

Caveats: short reviews, one dataset, the big model only ran on 100 rows because I was paying for it. The tags have no ground truth, so "agreement with the expensive model" is the best check I have.

If you have a backlog of text you have never been able to afford to read, I can tag all of it and hand you a spreadsheet you can filter. DM me.

Code and raw results: [link to repo]

#AI #DataAnalytics #CustomerExperience #LLM
